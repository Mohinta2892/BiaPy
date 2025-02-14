import tensorflow as tf
from tensorflow.keras.layers import (Input, concatenate, Conv2D, MaxPooling2D, AveragePooling2D, Conv2DTranspose, 
                                     UpSampling2D, average)
from tensorflow.keras.models import Model


# This code works if v2 is disabled, but fails if v2 is enabled.
tf.compat.v1.enable_v2_behavior

def MNet(input_shape):
    """Code copied from `Model_MNet <https://github.com/HzFu/MNet_DeepCDR/blob/master/mnet_deep_cdr/Model_MNet.py>`_.
       Made some minor changes to adapt the network to our specific case.
 
       Based on `Joint Optic Disc and Cup Segmentation Based on Multi-label Deep
       Network and Polar Transformation <https://arxiv.org/abs/1801.00926>`_.

       Parameters
       ----------

       input_shape : 3 int tuple
           Shape of input images.

       Returns
       -------

       model : Keras model
           MNet network model.


       Here is a picture of the network extracted from the original paper:

       .. image:: ../../img/models/MNet.jpg
           :width: 100%
           :align: center
    """

    img_input = Input(input_shape)

    scale_img_2 = AveragePooling2D(pool_size=(2, 2))(img_input)
    scale_img_3 = AveragePooling2D(pool_size=(2, 2))(scale_img_2)
    scale_img_4 = AveragePooling2D(pool_size=(2, 2))(scale_img_3)

    conv1 = Conv2D(32, (3, 3), padding='same', activation='relu', name='block1_conv1')(img_input)
    conv1 = Conv2D(32, (3, 3), padding='same', activation='relu', name='block1_conv2')(conv1)
    pool1 = MaxPooling2D(pool_size=(2, 2))(conv1)

    input2 = Conv2D(64, (3, 3), padding='same', activation='relu', name='block2_input1')(scale_img_2)
    input2 = concatenate([input2, pool1], axis=3)
    conv2 = Conv2D(64, (3, 3), padding='same', activation='relu', name='block2_conv1')(input2)
    conv2 = Conv2D(64, (3, 3), padding='same', activation='relu', name='block2_conv2')(conv2)
    pool2 = MaxPooling2D(pool_size=(2, 2))(conv2)

    input3 = Conv2D(128, (3, 3), padding='same', activation='relu', name='block3_input1')(scale_img_3)
    input3 = concatenate([input3, pool2], axis=3)
    conv3 = Conv2D(128, (3, 3), padding='same', activation='relu', name='block3_conv1')(input3)
    conv3 = Conv2D(128, (3, 3), padding='same', activation='relu', name='block3_conv2')(conv3)
    pool3 = MaxPooling2D(pool_size=(2, 2))(conv3)

    input4 = Conv2D(256, (3, 3), padding='same', activation='relu', name='block4_input1')(scale_img_4)
    input4 = concatenate([input4, pool3], axis=3)
    conv4 = Conv2D(256, (3, 3), padding='same', activation='relu', name='block4_conv1')(input4)
    conv4 = Conv2D(256, (3, 3), padding='same', activation='relu', name='block4_conv2')(conv4)
    pool4 = MaxPooling2D(pool_size=(2, 2))(conv4)

    conv5 = Conv2D(512, (3, 3), padding='same', activation='relu', name='block5_conv1')(pool4)
    conv5 = Conv2D(512, (3, 3), padding='same', activation='relu', name='block5_conv2')(conv5)

    up6 = concatenate(
        [Conv2DTranspose(256, (2, 2), strides=(2, 2), padding='same', name='block6_dconv')(conv5), conv4],
        axis=3)
    conv6 = Conv2D(256, (3, 3), padding='same', activation='relu', name='block6_conv1')(up6)
    conv6 = Conv2D(256, (3, 3), padding='same', activation='relu', name='block6_conv2')(conv6)

    up7 = concatenate(
        [Conv2DTranspose(128, (2, 2), strides=(2, 2), padding='same', name='block7_dconv')(conv6), conv3],
        axis=3)
    conv7 = Conv2D(128, (3, 3), padding='same', activation='relu', name='block7_conv1')(up7)
    conv7 = Conv2D(128, (3, 3), padding='same', activation='relu', name='block7_conv2')(conv7)

    up8 = concatenate([Conv2DTranspose(64, (2, 2), strides=(2, 2), padding='same', name='block8_dconv')(conv7), conv2],
                      axis=3)
    conv8 = Conv2D(64, (3, 3), padding='same', activation='relu', name='block8_conv1')(up8)
    conv8 = Conv2D(64, (3, 3), padding='same', activation='relu', name='block8_conv2')(conv8)

    up9 = concatenate([Conv2DTranspose(32, (2, 2), strides=(2, 2), padding='same', name='block9_dconv')(conv8), conv1],
                      axis=3)
    conv9 = Conv2D(32, (3, 3), padding='same', activation='relu', name='block9_conv1')(up9)
    conv9 = Conv2D(32, (3, 3), padding='same', activation='relu', name='block9_conv2')(conv9)

    side6 = UpSampling2D(size=(8, 8))(conv6)
    side7 = UpSampling2D(size=(4, 4))(conv7)
    side8 = UpSampling2D(size=(2, 2))(conv8)

    # Changes here to have just one class and use BCE as loss function
    out6 = Conv2D(1, (1, 1), activation='sigmoid', name='side_63')(side6)
    out7 = Conv2D(1, (1, 1), activation='sigmoid', name='side_73')(side7)
    out8 = Conv2D(1, (1, 1), activation='sigmoid', name='side_83')(side8)
    out9 = Conv2D(1, (1, 1), activation='sigmoid', name='side_93')(conv9)

    out10 = average([out6, out7, out8, out9])

    return Model(inputs=[img_input], outputs=[out6, out7, out8, out9, out10])

