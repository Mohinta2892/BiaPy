import os
import tensorflow as tf
import numpy as np
from tqdm import tqdm

from utils.util import  save_tif
from data.pre_processing import calculate_2D_volume_prob_map, calculate_3D_volume_prob_map, save_tif
from data.generators.pair_data_2D_generator import Pair2DImageDataGenerator
from data.generators.pair_data_3D_generator import Pair3DImageDataGenerator
from data.generators.single_data_2D_generator import Single2DImageDataGenerator
from data.generators.single_data_3D_generator import Single3DImageDataGenerator
from data.generators.test_pair_data_generators import test_pair_data_generator
from data.generators.test_single_data_generator import test_single_data_generator


def create_train_val_augmentors(cfg, X_train, Y_train, X_val, Y_val, num_gpus):
    """Create training and validation generators.

       Parameters
       ----------
       cfg : YACS CN object
           Configuration.

       X_train : 4D/5D Numpy array
           Training data. E.g. ``(num_of_images, y, x, channels)`` for ``2D`` or ``(num_of_images, z, y, x, channels)`` for ``3D``.

       Y_train : 4D/5D Numpy array
           Training data mask/class. E.g. ``(num_of_images, y, x, channels)`` for ``2D`` or ``(num_of_images, z, y, x, channels)`` for ``3D``
           in all the workflows except classification. For this last the shape is ``(num_of_images, class)`` for both ``2D`` and ``3D``.

       X_val : 4D/5D Numpy array
           Validation data mask/class. E.g. ``(num_of_images, y, x, channels)`` for ``2D`` or ``(num_of_images, z, y, x, channels)`` for ``3D``.

       Y_val : 4D/5D Numpy array
           Validation data mask/class. E.g. ``(num_of_images, y, x, channels)`` for ``2D`` or ``(num_of_images, z, y, x, channels)`` for ``3D``
           in all the workflows except classification. For this last the shape is ``(num_of_images, class)`` for both ``2D`` and ``3D``. 

       num_gpus : int
           Number of GPUs to use. 

       Returns
       -------
       train_generator : Pair2DImageDataGenerator/Single2DImageDataGenerator (2D) or Pair3DImageDataGenerator/Single3DImageDataGenerator (3D)
           Training data generator.

       val_generator : Pair2DImageDataGenerator/Single2DImageDataGenerator (2D) or Pair3DImageDataGenerator/Single3DImageDataGenerator (3D)
           Validation data generator.
    """

    # Calculate the probability map per image
    prob_map = None
    if cfg.DATA.PROBABILITY_MAP and cfg.DATA.EXTRACT_RANDOM_PATCH:
        if os.path.exists(cfg.PATHS.PROB_MAP_DIR):
            print("Loading probability map")
            prob_map_file = os.path.join(cfg.PATHS.PROB_MAP_DIR, cfg.PATHS.PROB_MAP_FILENAME)
            num_files = len(next(os.walk(cfg.PATHS.PROB_MAP_DIR))[2])
            prob_map = cfg.PATHS.PROB_MAP_DIR if num_files > 1 else np.load(prob_map_file)
        else:
            f_name = calculate_2D_volume_prob_map if cfg.PROBLEM.NDIM == '2D' else calculate_3D_volume_prob_map
            prob_map = f_name(Y_train, cfg.DATA.TRAIN.GT_PATH, cfg.DATA.W_FOREGROUND, cfg.DATA.W_BACKGROUND,
                              save_dir=cfg.PATHS.PROB_MAP_DIR)

    # Normalization checks
    custom_mean, custom_std = None, None
    if cfg.DATA.NORMALIZATION.TYPE == 'custom':
        if cfg.DATA.NORMALIZATION.CUSTOM_MEAN == -1 and cfg.DATA.NORMALIZATION.CUSTOM_STD == -1:
            print("Train/Val normalization: trying to load mean and std from {}".format(cfg.PATHS.MEAN_INFO_FILE))
            print("Train/Val normalization: trying to load std from {}".format(cfg.PATHS.STD_INFO_FILE))
            if not os.path.exists(cfg.PATHS.MEAN_INFO_FILE) or not os.path.exists(cfg.PATHS.STD_INFO_FILE):
                print("Train/Val normalization: mean and/or std files not found. Calculating it for the first time")
                custom_mean = np.mean(X_train)
                custom_std = np.std(X_train)
                os.makedirs(os.path.dirname(cfg.PATHS.MEAN_INFO_FILE), exist_ok=True)
                np.save(cfg.PATHS.MEAN_INFO_FILE, custom_mean)
                np.save(cfg.PATHS.STD_INFO_FILE, custom_std)
            else:
                custom_mean = np.load(cfg.PATHS.MEAN_INFO_FILE)
                custom_std = np.load(cfg.PATHS.STD_INFO_FILE)
                print("Train/Val normalization values loaded!")
        else:
            custom_mean = cfg.DATA.NORMALIZATION.CUSTOM_MEAN
            custom_std = cfg.DATA.NORMALIZATION.CUSTOM_STD
        print("Train/Val normalization: using mean {} and std: {}".format(custom_mean, custom_std))

    if cfg.PROBLEM.NDIM == '2D':
        if cfg.PROBLEM.TYPE == 'CLASSIFICATION' or \
            (cfg.PROBLEM.TYPE == 'SELF_SUPERVISED' and cfg.PROBLEM.SELF_SUPERVISED.PRETEXT_TASK == "masking"):
            f_name = Single2DImageDataGenerator 
        else:
            f_name = Pair2DImageDataGenerator
    else:
        if cfg.PROBLEM.TYPE == 'CLASSIFICATION' or \
            (cfg.PROBLEM.TYPE == 'SELF_SUPERVISED' and cfg.PROBLEM.SELF_SUPERVISED.PRETEXT_TASK == "masking"):
            f_name = Single3DImageDataGenerator 
        else:
            f_name = Pair3DImageDataGenerator
    
    ndim = 3 if cfg.PROBLEM.NDIM == "3D" else 2
    if cfg.PROBLEM.TYPE != 'DENOISING':
        data_paths = [cfg.DATA.TRAIN.PATH, cfg.DATA.TRAIN.GT_PATH] 
    else:
        data_paths = [cfg.DATA.TRAIN.PATH] 
    if cfg.PROBLEM.TYPE == 'CLASSIFICATION' or \
        (cfg.PROBLEM.TYPE == 'SELF_SUPERVISED' and cfg.PROBLEM.SELF_SUPERVISED.PRETEXT_TASK == "masking"):
        r_shape = cfg.DATA.PATCH_SIZE
        if cfg.MODEL.ARCHITECTURE == 'EfficientNetB0' and cfg.DATA.PATCH_SIZE[:-1] != (224,224):
            r_shape = (224,224)+(cfg.DATA.PATCH_SIZE[-1],) 
            print("Changing patch size from {} to {} to use EfficientNetB0".format(cfg.DATA.PATCH_SIZE[:-1], r_shape))
        ptype = "classification" if cfg.PROBLEM.TYPE == 'CLASSIFICATION' else "mae"
        dic = dict(ndim=ndim, X=X_train, Y=Y_train, data_path=cfg.DATA.TRAIN.PATH, ptype=ptype, n_classes=cfg.MODEL.N_CLASSES,
            seed=cfg.SYSTEM.SEED, da=cfg.AUGMENTOR.ENABLE, in_memory=cfg.DATA.TRAIN.IN_MEMORY, da_prob=cfg.AUGMENTOR.DA_PROB,
            rotation90=cfg.AUGMENTOR.ROT90, rand_rot=cfg.AUGMENTOR.RANDOM_ROT, rnd_rot_range=cfg.AUGMENTOR.RANDOM_ROT_RANGE,
            shear=cfg.AUGMENTOR.SHEAR, shear_range=cfg.AUGMENTOR.SHEAR_RANGE, zoom=cfg.AUGMENTOR.ZOOM,
            zoom_range=cfg.AUGMENTOR.ZOOM_RANGE, shift=cfg.AUGMENTOR.SHIFT, shift_range=cfg.AUGMENTOR.SHIFT_RANGE,
            affine_mode=cfg.AUGMENTOR.AFFINE_MODE, vflip=cfg.AUGMENTOR.VFLIP, hflip=cfg.AUGMENTOR.HFLIP,
            elastic=cfg.AUGMENTOR.ELASTIC, e_alpha=cfg.AUGMENTOR.E_ALPHA, e_sigma=cfg.AUGMENTOR.E_SIGMA,
            e_mode=cfg.AUGMENTOR.E_MODE, g_blur=cfg.AUGMENTOR.G_BLUR, g_sigma=cfg.AUGMENTOR.G_SIGMA,
            median_blur=cfg.AUGMENTOR.MEDIAN_BLUR, mb_kernel=cfg.AUGMENTOR.MB_KERNEL, motion_blur=cfg.AUGMENTOR.MOTION_BLUR,
            motb_k_range=cfg.AUGMENTOR.MOTB_K_RANGE, gamma_contrast=cfg.AUGMENTOR.GAMMA_CONTRAST,
            gc_gamma=cfg.AUGMENTOR.GC_GAMMA, dropout=cfg.AUGMENTOR.DROPOUT, drop_range=cfg.AUGMENTOR.DROP_RANGE,
            resize_shape=r_shape, norm_custom_mean=custom_mean, norm_custom_std=custom_std)
    else:
        dic = dict(ndim=ndim, X=X_train, Y=Y_train, seed=cfg.SYSTEM.SEED, in_memory=cfg.DATA.TRAIN.IN_MEMORY, 
            data_paths=data_paths, da=cfg.AUGMENTOR.ENABLE,
            da_prob=cfg.AUGMENTOR.DA_PROB, rotation90=cfg.AUGMENTOR.ROT90, rand_rot=cfg.AUGMENTOR.RANDOM_ROT,
            rnd_rot_range=cfg.AUGMENTOR.RANDOM_ROT_RANGE, shear=cfg.AUGMENTOR.SHEAR, shear_range=cfg.AUGMENTOR.SHEAR_RANGE,
            zoom=cfg.AUGMENTOR.ZOOM, zoom_range=cfg.AUGMENTOR.ZOOM_RANGE, shift=cfg.AUGMENTOR.SHIFT,
            affine_mode=cfg.AUGMENTOR.AFFINE_MODE, shift_range=cfg.AUGMENTOR.SHIFT_RANGE, vflip=cfg.AUGMENTOR.VFLIP,
            hflip=cfg.AUGMENTOR.HFLIP, elastic=cfg.AUGMENTOR.ELASTIC, e_alpha=cfg.AUGMENTOR.E_ALPHA,
            e_sigma=cfg.AUGMENTOR.E_SIGMA, e_mode=cfg.AUGMENTOR.E_MODE, g_blur=cfg.AUGMENTOR.G_BLUR,
            g_sigma=cfg.AUGMENTOR.G_SIGMA, median_blur=cfg.AUGMENTOR.MEDIAN_BLUR, mb_kernel=cfg.AUGMENTOR.MB_KERNEL,
            motion_blur=cfg.AUGMENTOR.MOTION_BLUR, motb_k_range=cfg.AUGMENTOR.MOTB_K_RANGE,
            gamma_contrast=cfg.AUGMENTOR.GAMMA_CONTRAST, gc_gamma=cfg.AUGMENTOR.GC_GAMMA, brightness=cfg.AUGMENTOR.BRIGHTNESS,
            brightness_factor=cfg.AUGMENTOR.BRIGHTNESS_FACTOR, brightness_mode=cfg.AUGMENTOR.BRIGHTNESS_MODE,
            contrast=cfg.AUGMENTOR.CONTRAST, contrast_factor=cfg.AUGMENTOR.CONTRAST_FACTOR,
            contrast_mode=cfg.AUGMENTOR.CONTRAST_MODE, brightness_em=cfg.AUGMENTOR.BRIGHTNESS_EM,
            brightness_em_factor=cfg.AUGMENTOR.BRIGHTNESS_EM_FACTOR, brightness_em_mode=cfg.AUGMENTOR.BRIGHTNESS_EM_MODE,
            contrast_em=cfg.AUGMENTOR.CONTRAST_EM, contrast_em_factor=cfg.AUGMENTOR.CONTRAST_EM_FACTOR,
            contrast_em_mode=cfg.AUGMENTOR.CONTRAST_EM_MODE, dropout=cfg.AUGMENTOR.DROPOUT,
            drop_range=cfg.AUGMENTOR.DROP_RANGE, cutout=cfg.AUGMENTOR.CUTOUT,
            cout_nb_iterations=cfg.AUGMENTOR.COUT_NB_ITERATIONS, cout_size=cfg.AUGMENTOR.COUT_SIZE,
            cout_cval=cfg.AUGMENTOR.COUT_CVAL, cout_apply_to_mask=cfg.AUGMENTOR.COUT_APPLY_TO_MASK,
            cutblur=cfg.AUGMENTOR.CUTBLUR, cblur_size=cfg.AUGMENTOR.CBLUR_SIZE, cblur_down_range=cfg.AUGMENTOR.CBLUR_DOWN_RANGE,
            cblur_inside=cfg.AUGMENTOR.CBLUR_INSIDE, cutmix=cfg.AUGMENTOR.CUTMIX, cmix_size=cfg.AUGMENTOR.CMIX_SIZE,
            cutnoise=cfg.AUGMENTOR.CUTNOISE, cnoise_size=cfg.AUGMENTOR.CNOISE_SIZE,
            cnoise_nb_iterations=cfg.AUGMENTOR.CNOISE_NB_ITERATIONS, cnoise_scale=cfg.AUGMENTOR.CNOISE_SCALE,
            misalignment=cfg.AUGMENTOR.MISALIGNMENT, ms_displacement=cfg.AUGMENTOR.MS_DISPLACEMENT,
            ms_rotate_ratio=cfg.AUGMENTOR.MS_ROTATE_RATIO, missing_sections=cfg.AUGMENTOR.MISSING_SECTIONS,
            missp_iterations=cfg.AUGMENTOR.MISSP_ITERATIONS, grayscale=cfg.AUGMENTOR.GRAYSCALE,
            channel_shuffle=cfg.AUGMENTOR.CHANNEL_SHUFFLE, gridmask=cfg.AUGMENTOR.GRIDMASK,
            grid_ratio=cfg.AUGMENTOR.GRID_RATIO, grid_d_range=cfg.AUGMENTOR.GRID_D_RANGE, grid_rotate=cfg.AUGMENTOR.GRID_ROTATE,
            grid_invert=cfg.AUGMENTOR.GRID_INVERT, gaussian_noise=cfg.AUGMENTOR.GAUSSIAN_NOISE, 
            gaussian_noise_mean=cfg.AUGMENTOR.GAUSSIAN_NOISE_MEAN, gaussian_noise_var=cfg.AUGMENTOR.GAUSSIAN_NOISE_VAR,
            gaussian_noise_use_input_img_mean_and_var=cfg.AUGMENTOR.GAUSSIAN_NOISE_USE_INPUT_IMG_MEAN_AND_VAR, 
            poisson_noise=cfg.AUGMENTOR.POISSON_NOISE, salt=cfg.AUGMENTOR.SALT, salt_amount=cfg.AUGMENTOR.SALT_AMOUNT,
            pepper=cfg.AUGMENTOR.PEPPER, pepper_amount=cfg.AUGMENTOR.PEPPER_AMOUNT, salt_and_pepper=cfg.AUGMENTOR.SALT_AND_PEPPER, 
            salt_pep_amount=cfg.AUGMENTOR.SALT_AND_PEPPER_AMOUNT, salt_pep_proportion=cfg.AUGMENTOR.SALT_AND_PEPPER_PROP,
            shape=cfg.DATA.PATCH_SIZE, resolution=cfg.DATA.TRAIN.RESOLUTION, random_crops_in_DA=cfg.DATA.EXTRACT_RANDOM_PATCH, 
            prob_map=prob_map, n_classes=cfg.MODEL.N_CLASSES, extra_data_factor=cfg.DATA.TRAIN.REPLICATE, 
            norm_custom_mean=custom_mean, norm_custom_std=custom_std, random_crop_scale=cfg.PROBLEM.SUPER_RESOLUTION.UPSCALING)

        if cfg.PROBLEM.NDIM == '3D':
            dic['zflip'] = cfg.AUGMENTOR.ZFLIP

        if cfg.PROBLEM.TYPE == 'INSTANCE_SEG':
            dic['instance_problem'] = True
        elif cfg.PROBLEM.TYPE == 'SUPER_RESOLUTION':
            dic['normalizeY'] = 'none'
        elif cfg.PROBLEM.TYPE == 'SELF_SUPERVISED':
            dic['normalizeY'] = 'as_image'
        elif cfg.PROBLEM.TYPE == 'DENOISING':
            dic['n2v']=True
            dic['n2v_perc_pix'] = cfg.PROBLEM.DENOISING.N2V_PERC_PIX
            dic['n2v_manipulator'] = cfg.PROBLEM.DENOISING.N2V_MANIPULATOR
            dic['n2v_neighborhood_radius'] = cfg.PROBLEM.DENOISING.N2V_NEIGHBORHOOD_RADIUS
            dic['n2v_structMask'] = np.array([[0,1,1,1,1,1,1,1,1,1,0]]) if cfg.PROBLEM.DENOISING.N2V_STRUCTMASK else None

    print("Initializing train data generator . . .")
    train_generator = f_name(**dic)
    data_norm = train_generator.get_data_normalization()

    print("Initializing val data generator . . .")
    if cfg.PROBLEM.TYPE == 'CLASSIFICATION' or \
        (cfg.PROBLEM.TYPE == 'SELF_SUPERVISED' and cfg.PROBLEM.SELF_SUPERVISED.PRETEXT_TASK == "masking"):
        ptype = "classification" if cfg.PROBLEM.TYPE == 'CLASSIFICATION' else "mae"
        val_generator = f_name(ndim=ndim, X=X_val, Y=Y_val, data_path=cfg.DATA.VAL.PATH, ptype=ptype, n_classes=cfg.MODEL.N_CLASSES, 
            in_memory=cfg.DATA.VAL.IN_MEMORY, seed=cfg.SYSTEM.SEED, da=False, resize_shape=r_shape, 
            norm_custom_mean=custom_mean, norm_custom_std=custom_std)
    else:
        if cfg.PROBLEM.TYPE != 'DENOISING':
            data_paths = [cfg.DATA.TRAIN.PATH, cfg.DATA.TRAIN.GT_PATH] 
        else:
            data_paths = [cfg.DATA.TRAIN.PATH] 
        dic = dict(ndim=ndim, X=X_val, Y=Y_val, in_memory=cfg.DATA.VAL.IN_MEMORY,
            data_paths=data_paths, da=False, shape=cfg.DATA.PATCH_SIZE,
            random_crops_in_DA=cfg.DATA.EXTRACT_RANDOM_PATCH, val=True, n_classes=cfg.MODEL.N_CLASSES, 
            seed=cfg.SYSTEM.SEED, norm_custom_mean=custom_mean, norm_custom_std=custom_std, resolution=cfg.DATA.VAL.RESOLUTION,
            random_crop_scale=cfg.PROBLEM.SUPER_RESOLUTION.UPSCALING)
        if cfg.PROBLEM.TYPE == 'INSTANCE_SEG': 
            dic['instance_problem'] = True
        elif cfg.PROBLEM.TYPE == 'SUPER_RESOLUTION':
            dic['normalizeY'] = 'none'
        elif cfg.PROBLEM.TYPE == 'SELF_SUPERVISED':
            dic['normalizeY'] = 'as_image'
        elif cfg.PROBLEM.TYPE == 'DENOISING':
            dic['n2v'] = True
            dic['n2v_perc_pix'] = cfg.PROBLEM.DENOISING.N2V_PERC_PIX
            dic['n2v_manipulator'] = cfg.PROBLEM.DENOISING.N2V_MANIPULATOR
            dic['n2v_neighborhood_radius'] = cfg.PROBLEM.DENOISING.N2V_NEIGHBORHOOD_RADIUS
            
        val_generator = f_name(**dic)

    # Generate examples of data augmentation
    if cfg.AUGMENTOR.AUG_SAMPLES:
        print("Creating generator samples . . .")
        train_generator.get_transformed_samples(
            cfg.AUGMENTOR.AUG_NUM_SAMPLES, save_to_dir=True, train=False, out_dir=cfg.PATHS.DA_SAMPLES,
            draw_grid=cfg.AUGMENTOR.DRAW_GRID)

    # Decide number of processes
    num_parallel_calls = tf.data.AUTOTUNE if cfg.SYSTEM.NUM_CPUS == -1 else cfg.SYSTEM.NUM_CPUS
    
    out_dtype = tf.uint16 if cfg.PROBLEM.TYPE == 'CLASSIFICATION' else tf.float32

    # Paralelize as explained in: 
    # https://medium.com/@acordier/tf-data-dataset-generators-with-parallelization-the-easy-way-b5c5f7d2a18
    # Single item generators
    if cfg.PROBLEM.TYPE == 'SELF_SUPERVISED' and cfg.PROBLEM.SELF_SUPERVISED.PRETEXT_TASK == "masking":
        def train_func(i):
            i = i.numpy() 
            x = train_generator.getitem(i)
            return x
        def val_func(i):
            i = i.numpy() 
            x = val_generator.getitem(i)
            return x
        train_index_generator = list(range(len(train_generator))) 
        val_index_generator = list(range(len(val_generator))) 
        tdataset = tf.data.Dataset.from_generator(lambda: train_index_generator, tf.uint64)
        vdataset = tf.data.Dataset.from_generator(lambda: val_index_generator, tf.uint64)
        train_dataset = tdataset.map(lambda i: tf.py_function(
            func=train_func, inp=[i], Tout=[tf.float32]), num_parallel_calls=num_parallel_calls)
        val_dataset = vdataset.map(lambda i: tf.py_function(
            func=val_func, inp=[i], Tout=[tf.float32]), num_parallel_calls=num_parallel_calls)

        def _fixup_shape(x):
            x.set_shape((None, )+cfg.DATA.PATCH_SIZE) 
            return x
    # Double item generators
    else:
        def train_func(i):
            i = i.numpy() 
            x, y = train_generator.getitem(i)
            return x, y
        def val_func(i):
            i = i.numpy() 
            x, y = val_generator.getitem(i)
            return x, y
        train_index_generator = list(range(len(train_generator))) 
        val_index_generator = list(range(len(val_generator))) 
        tdataset = tf.data.Dataset.from_generator(lambda: train_index_generator, tf.uint64)
        vdataset = tf.data.Dataset.from_generator(lambda: val_index_generator, tf.uint64)
        train_dataset = tdataset.map(lambda i: tf.py_function(
            func=train_func, inp=[i], Tout=[tf.float32, out_dtype]), num_parallel_calls=num_parallel_calls)
        val_dataset = vdataset.map(lambda i: tf.py_function(
            func=val_func, inp=[i], Tout=[tf.float32, out_dtype]), num_parallel_calls=num_parallel_calls)

        def _fixup_shape(x, y):
            x.set_shape([None, ]*(len(cfg.DATA.PATCH_SIZE)+1)) 
            if cfg.PROBLEM.TYPE != 'CLASSIFICATION':
                y.set_shape([None, ]*(len(cfg.DATA.PATCH_SIZE)+1)) 
            else:
                y.set_shape((None)) 
            return x, y

    global_batch_size = cfg.TRAIN.BATCH_SIZE * num_gpus
    train_dataset = train_dataset.batch(global_batch_size).map(_fixup_shape)
    val_dataset = val_dataset.batch(global_batch_size).map(_fixup_shape)

    if cfg.AUGMENTOR.SHUFFLE_TRAIN_DATA_EACH_EPOCH:
        train_dataset = train_dataset.shuffle(len(train_generator), seed=cfg.SYSTEM.SEED)

    if cfg.AUGMENTOR.SHUFFLE_VAL_DATA_EACH_EPOCH:
        val_dataset = val_dataset.shuffle(len(val_generator), seed=cfg.SYSTEM.SEED)

    # Fixing some error with dataset length: https://discuss.tensorflow.org/t/typeerror-dataset-length-is-unknown-tensorflow/948/9
    # Using assert_cardinality to add the number of samples (input)
    len_train = int(np.ceil(len(train_generator)/global_batch_size))
    len_val = int(np.ceil(len(val_generator)/global_batch_size))
    train_dataset = train_dataset.apply(tf.data.experimental.assert_cardinality(len_train))
    val_dataset = val_dataset.apply(tf.data.experimental.assert_cardinality(len_val))

    train_dataset = train_dataset.prefetch(tf.data.AUTOTUNE)
    val_dataset = val_dataset.prefetch(tf.data.AUTOTUNE)

    # To avoid sharding swap message from AutoShardPolicy.FILE to AutoShardPolicy.DATA
    options = tf.data.Options()
    options.experimental_distribute.auto_shard_policy = tf.data.experimental.AutoShardPolicy.DATA
    train_dataset = train_dataset.with_options(options)
    val_dataset = val_dataset.with_options(options)

    return train_dataset, val_dataset, data_norm

def create_test_augmentor(cfg, X_test, Y_test, cross_val_samples_ids):
    """
    Create test data generator.

    Parameters
    ----------
    cfg : YACS CN object
        Configuration.

    X_test : 4D Numpy array
        Test data. E.g. ``(num_of_images, y, x, channels)`` for ``2D`` or ``(num_of_images, z, y, x, channels)`` for ``3D``.

    Y_test : 4D Numpy array
        Test data mask/class. E.g. ``(num_of_images, y, x, channels)`` for ``2D`` or ``(num_of_images, z, y, x, channels)`` for ``3D``
        in all the workflows except classification. For this last the shape is ``(num_of_images, class)`` for both ``2D`` and ``3D``.

    cross_val_samples_ids : List of ints, optional
        When cross validation is used training data samples' id are passed. 

    Returns
    -------
    test_generator : test_pair_data_generator
        Test data generator.
    """
    custom_mean, custom_std = None, None
    if cfg.DATA.NORMALIZATION.TYPE == 'custom':
        if cfg.DATA.NORMALIZATION.CUSTOM_MEAN == -1 and cfg.DATA.NORMALIZATION.CUSTOM_STD == -1:
            print("Test normalization: trying to load mean and std from {}".format(cfg.PATHS.MEAN_INFO_FILE))
            print("Test normalization: trying to load std from {}".format(cfg.PATHS.STD_INFO_FILE))
            if not os.path.exists(cfg.PATHS.MEAN_INFO_FILE) or not os.path.exists(cfg.PATHS.STD_INFO_FILE):
                raise FileNotFoundError("Not mean/std files found in {} and {}"
                    .format(cfg.PATHS.MEAN_INFO_FILE, cfg.PATHS.STD_INFO_FILE))
            custom_mean = np.load(cfg.PATHS.MEAN_INFO_FILE)
            custom_std = np.load(cfg.PATHS.STD_INFO_FILE)
        else:
            custom_mean = cfg.DATA.NORMALIZATION.CUSTOM_MEAN
            custom_std = cfg.DATA.NORMALIZATION.CUSTOM_STD
        print("Test normalization: using mean {} and std: {}".format(custom_mean, custom_std))

    instance_problem = True if cfg.PROBLEM.TYPE == 'INSTANCE_SEG' else False
    normalizeY='as_mask'
    provide_Y=cfg.DATA.TEST.LOAD_GT
    if cfg.PROBLEM.TYPE == 'SUPER_RESOLUTION':
        normalizeY = 'none'
    elif cfg.PROBLEM.TYPE == 'SELF_SUPERVISED':
        normalizeY = 'as_image'
        provide_Y = True if cfg.PROBLEM.SELF_SUPERVISED.PRETEXT_TASK == "crappify" else False
    
    ndim = 3 if cfg.PROBLEM.NDIM == "3D" else 2
    dic = dict(ndim=ndim, X=X_test, d_path=cfg.DATA.TEST.PATH if cross_val_samples_ids is None else cfg.DATA.TRAIN.PATH, 
        provide_Y=provide_Y, Y=Y_test, dm_path=cfg.DATA.TEST.GT_PATH if cross_val_samples_ids is None else cfg.DATA.TRAIN.GT_PATH,
        seed=cfg.SYSTEM.SEED, instance_problem=instance_problem, norm_custom_mean=custom_mean, norm_custom_std=custom_std,
        sample_ids=cross_val_samples_ids)        
        
    if cfg.PROBLEM.TYPE == 'CLASSIFICATION' or \
        (cfg.PROBLEM.TYPE == 'SELF_SUPERVISED' and cfg.PROBLEM.SELF_SUPERVISED.PRETEXT_TASK == "masking"):
        gen_name = test_single_data_generator 
        r_shape = cfg.DATA.PATCH_SIZE
        if cfg.MODEL.ARCHITECTURE == 'EfficientNetB0' and cfg.DATA.PATCH_SIZE[:-1] != (224,224):
            r_shape = (224,224)+(cfg.DATA.PATCH_SIZE[-1],) 
            print("Changing patch size from {} to {} to use EfficientNetB0".format(cfg.DATA.PATCH_SIZE[:-1], r_shape))
        if cfg.PROBLEM.TYPE == 'CLASSIFICATION':
            dic['crop_center'] = True
            dic['resize_shape'] = r_shape
            dic['ptype'] = "classification"
        else: # SSL
            dic['ptype'] = "mae"
    else:
        gen_name = test_pair_data_generator
        dic['normalizeY'] = normalizeY 
        
    test_generator = gen_name(**dic)
    data_norm = test_generator.get_data_normalization()
    return test_generator, data_norm


def check_generator_consistence(gen, data_out_dir, mask_out_dir, filenames=None):
    """Save all data of a generator in the given path.

       Parameters
       ----------
       gen : Pair2DImageDataGenerator/Single2DImageDataGenerator (2D) or Pair3DImageDataGenerator/Single3DImageDataGenerator (3D)
           Generator to extract the data from.

       data_out_dir : str
           Path to store the generator data samples.

       mask_out_dir : str
           Path to store the generator data mask samples.

       Filenames : List, optional
           Filenames that should be used when saving each image.
    """

    print("Check generator . . .")
    it = iter(gen)
    
    c = 0
    for i in tqdm(range(len(gen))):
        sample = next(it)
        X_test, Y_test = sample
        
        for k in range(len(X_test)):
            fil = filenames[c] if filenames is not None else ["sample_"+str(c)+".tif"]
            save_tif(np.expand_dims(X_test[k],0), data_out_dir, fil, verbose=False)
            save_tif(np.expand_dims(Y_test[k],0), mask_out_dir, fil, verbose=False)
            c += 1
