from __future__ import print_function
from keras.preprocessing.image import load_img, save_img, img_to_array
import numpy as np
from scipy.optimize import fmin_l_bfgs_b
import time
import argparse
from keras.applications import vgg19
from keras import backend as K
import os
import gc

def main(max_index, base_image_path_dir, style_reference_image_path, result_prefix_dir, iterations=11, total_variation_weight=1.0, style_weight=1.0, content_weight=0.025):

    img_index = max_index
    base_image_path = base_image_path_dir + str(img_index) + '.png'
    style_reference_image_path = style_reference_image_path
    result_prefix = result_prefix_dir
    iterations = iterations
    total_variation_weight = total_variation_weight
    style_weight = style_weight
    content_weight = content_weight

    if not os.path.exists(result_prefix):
        os.makedirs(result_prefix)

    # dimensions of the generated picture.
    # width, height = load_img(base_image_path).size
    img_nrows = 256
    img_ncols = 256

    # util function to open, resize and format pictures into appropriate tensors


    def preprocess_image(image_path):
        img = load_img(image_path, target_size=(img_nrows, img_ncols))
        img = img_to_array(img)
        img = np.expand_dims(img, axis=0)
        img = vgg19.preprocess_input(img)
        return img

    # util function to convert a tensor into a valid image


    def deprocess_image(x):
        if K.image_data_format() == 'channels_first':
            x = x.reshape((3, img_nrows, img_ncols))
            x = x.transpose((1, 2, 0))
        else:
            x = x.reshape((img_nrows, img_ncols, 3))
        # Remove zero-center by mean pixel
        x[:, :, 0] += 103.939
        x[:, :, 1] += 116.779
        x[:, :, 2] += 123.68
        # 'BGR'->'RGB'
        x = x[:, :, ::-1]
        x = np.clip(x, 0, 255).astype('uint8')
        return x

    # get tensor representations of our images
    base_image = K.variable(preprocess_image(base_image_path))
    style_reference_image = K.variable(preprocess_image(style_reference_image_path))

    # this will contain our generated image
    if K.image_data_format() == 'channels_first':
        combination_image = K.placeholder((1, 3, img_nrows, img_ncols))
    else:
        combination_image = K.placeholder((1, img_nrows, img_ncols, 3))

    # combine the 3 images into a single Keras tensor
    input_tensor = K.concatenate([base_image, style_reference_image, combination_image], axis=0)

    # build the VGG16 network with our 3 images as input
    # the model will be loaded with pre-trained ImageNet weights
    model = vgg19.VGG19(input_tensor=input_tensor, weights='imagenet', include_top=False)
    print('Model loaded.')

    # get the symbolic outputs of each "key" layer (we gave them unique names).
    outputs_dict = dict([(layer.name, layer.output) for layer in model.layers])

                
    for i in range(max_index, max_index+50):
        img_index = i
        base_image_path = base_image_path_dir + str(img_index) + '.png'




        # compute the neural style loss
        # first we need to define 4 util functions

        # the gram matrix of an image tensor (feature-wise outer product)


        def gram_matrix(x):
            assert K.ndim(x) == 3
            if K.image_data_format() == 'channels_first':
                features = K.batch_flatten(x)
            else:
                features = K.batch_flatten(K.permute_dimensions(x, (2, 0, 1)))
            gram = K.dot(features, K.transpose(features))
            return gram

        # the "style loss" is designed to maintain
        # the style of the reference image in the generated image.
        # It is based on the gram matrices (which capture style) of
        # feature maps from the style reference image
        # and from the generated image


        def style_loss(style, combination):
            assert K.ndim(style) == 3
            assert K.ndim(combination) == 3
            S = gram_matrix(style)
            C = gram_matrix(combination)
            channels = 3
            size = img_nrows * img_ncols
            return K.sum(K.square(S - C)) / (4. * (channels ** 2) * (size ** 2))

        # an auxiliary loss function
        # designed to maintain the "content" of the
        # base image in the generated image


        def content_loss(base, combination):
            return K.sum(K.square(combination - base))

        # the 3rd loss function, total variation loss,
        # designed to keep the generated image locally coherent


        def total_variation_loss(x):
            assert K.ndim(x) == 4
            if K.image_data_format() == 'channels_first':
                a = K.square(x[:, :, :img_nrows - 1, :img_ncols - 1] - x[:, :, 1:, :img_ncols - 1])
                b = K.square(x[:, :, :img_nrows - 1, :img_ncols - 1] - x[:, :, :img_nrows - 1, 1:])
            else:
                a = K.square(x[:, :img_nrows - 1, :img_ncols - 1, :] - x[:, 1:, :img_ncols - 1, :])
                b = K.square(x[:, :img_nrows - 1, :img_ncols - 1, :] - x[:, :img_nrows - 1, 1:, :])
            return K.sum(K.pow(a + b, 1.25))

        # combine these loss functions into a single scalar
        loss = K.variable(0.)
        layer_features = outputs_dict['block5_conv2']
        base_image_features = layer_features[0, :, :, :]
        combination_features = layer_features[2, :, :, :]
        loss += content_weight * content_loss(base_image_features, combination_features)

        feature_layers = ['block1_conv1', 'block2_conv1', 'block3_conv1', 'block4_conv1', 'block5_conv1']
        for layer_name in feature_layers:
            layer_features = outputs_dict[layer_name]
            style_reference_features = layer_features[1, :, :, :]
            combination_features = layer_features[2, :, :, :]
            sl = style_loss(style_reference_features, combination_features)
            loss += (style_weight / len(feature_layers)) * sl
        loss += total_variation_weight * total_variation_loss(combination_image)

        # get the gradients of the generated image wrt the loss
        grads = K.gradients(loss, combination_image)

        outputs = [loss]
        if isinstance(grads, (list, tuple)):
            outputs += grads
        else:
            outputs.append(grads)

        f_outputs = K.function([combination_image], outputs)


        def eval_loss_and_grads(x):
            if K.image_data_format() == 'channels_first':
                x = x.reshape((1, 3, img_nrows, img_ncols))
            else:
                x = x.reshape((1, img_nrows, img_ncols, 3))
            outs = f_outputs([x])
            loss_value = outs[0]
            if len(outs[1:]) == 1:
                grad_values = outs[1].flatten().astype('float64')
            else:
                grad_values = np.array(outs[1:]).flatten().astype('float64')
            return loss_value, grad_values

        # this Evaluator class makes it possible
        # to compute loss and gradients in one pass
        # while retrieving them via two separate functions,
        # "loss" and "grads". This is done because scipy.optimize
        # requires separate functions for loss and gradients,
        # but computing them separately would be inefficient.


        class Evaluator(object):

            def __init__(self):
                self.loss_value = None
                self.grads_values = None

            def loss(self, x):
                assert self.loss_value is None
                loss_value, grad_values = eval_loss_and_grads(x)
                self.loss_value = loss_value
                self.grad_values = grad_values
                return self.loss_value

            def grads(self, x):
                assert self.loss_value is not None
                grad_values = np.copy(self.grad_values)
                self.loss_value = None
                self.grad_values = None
                return grad_values

        evaluator = Evaluator()

        # run scipy-based optimization (L-BFGS) over the pixels of the generated image
        # so as to minimize the neural style loss
        x = preprocess_image(base_image_path)

        start_time = time.time()
        for i in range(iterations):
            print('Start of iteration', i)
            x, min_val, info = fmin_l_bfgs_b(evaluator.loss, x.flatten(), fprime=evaluator.grads, maxfun=20)
            print('Current loss value:', min_val)
            # save current generated image
            if i == 10:
                img = deprocess_image(x.copy())
                fname = '%s%s.png' % (result_prefix, str(img_index))
                save_img(fname, img)
                end_time = time.time()
                print('Image saved as', fname)
                print('Iteration %d completed in %ds' % (i, end_time - start_time))
                print('Total completed in %ds' % (end_time - begin_time))
                print()
            
def get_max():
    file_list = list()
    path = '/home/iis/wuling31715/captcha_generator/mnist/halftone_size256/x_train/'
    for i in os.listdir(path):
        if '.png' in i:
            j = int(i.replace('.png', ''))
            file_list.append(j)
    if len(file_list) == 0:
        file_list.append(0)
    return max(file_list)

begin_time = time.time()
max_index = get_max() + 1
print('Start from: %s' % str(max_index))
main(max_index, '/home/iis/wuling31715/captcha_generator/mnist/channel3_size256/x_train/', '/home/iis/wuling31715/captcha_generator/style/halftone_256.png', '/home/iis/wuling31715/captcha_generator/mnist/halftone_size256/x_train/')