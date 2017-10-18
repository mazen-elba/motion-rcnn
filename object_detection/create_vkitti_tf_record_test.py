# --------------------------------------------------------
# Motion R-CNN
# Licensed under The MIT License [see LICENSE for details]
# Written by Simon Meister
# --------------------------------------------------------
from __future__ import absolute_import, division, print_function

import sys
import os
import glob
import shutil

import numpy as np
import PIL.Image as Image
from PIL import ImageDraw
import tensorflow as tf
import matplotlib.pyplot as plt

from cityscapesscripts.helpers.labels import trainId2label

from object_detection.data_decoders.tf_example_decoder import TfExampleDecoder
from object_detection.utils.flow_util import flow_to_color, flow_error_image, flow_error_avg
from object_detection.utils.np_motion_util import dense_flow_from_motion


with tf.Graph().as_default():
    file_pattern = 'object_detection/data/records/vkitti_val/00000-of-00000.record'
    tfrecords = glob.glob(file_pattern)

    with tf.device('/cpu:0'):
        filename_queue = tf.train.string_input_producer(
            tfrecords, capacity=len(tfrecords))
        reader = tf.TFRecordReader()
        _, serialized_example = reader.read(filename_queue)
        example = TfExampleDecoder().decode(serialized_example)
        flow_color = flow_to_color(tf.expand_dims(example['groundtruth_flow'], 0))[0, :, :, :]
        print(example.keys())

    sess = tf.Session()
    init_op = tf.group(
        tf.global_variables_initializer(),
        tf.local_variables_initializer())

    sess.run(init_op)

    tf.train.start_queue_runners(sess=sess)
    out_dir = 'object_detection/output/tests/vkitti/'
    if os.path.isdir(out_dir):
      shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    with sess.as_default():
        for i in range(100):
            example_np, flow_color_np = sess.run([example, flow_color])
            img_id_np = example_np['filename']
            image_np = example_np['image']
            gt_boxes_np = example_np['groundtruth_boxes']
            gt_classes_np = example_np['groundtruth_classes']
            gt_masks_np = example_np['groundtruth_instance_masks']
            height, width = image_np.shape[:2]
            num_instances_np = gt_masks_np.shape[0]
            image_np = np.squeeze(image_np)
            depth_np = example_np['groundtruth_depth']

            # compose flow from motion gt
            composed_flow_np = dense_flow_from_motion(
                depth_np,
                example_np['groundtruth_instance_motions'],
                gt_masks_np,
                example_np['groundtruth_camera_motion'],
                example_np['camera_intrinsics'])
            composed_flow_const = tf.expand_dims(composed_flow_np, 0)
            gt_flow_np = example_np['groundtruth_flow']
            gt_mask_np = np.float32((gt_flow_np[:, :, 0] * gt_flow_np[:, :, 1]) != np.nan)
            gt_flow_np = np.nan_to_num(gt_flow_np)
            gt_flow_const = tf.expand_dims(gt_flow_np, 0)
            gt_mask_const = tf.expand_dims(tf.expand_dims(gt_mask_np, 0), 3)
            composed_flow_color = flow_to_color(composed_flow_const)[0, :, :, :]
            flow_error = flow_error_image(composed_flow_const, gt_flow_const,
                                          gt_mask_const, log_colors=False)[0, :, :, :]
            epe = flow_error_avg(composed_flow_const, gt_flow_const, gt_mask_const)
            composed_flow_color_np, flow_error_np, epe_np = sess.run(
                [composed_flow_color, flow_error, epe])


            print('image_id: {}, instances: {}, shape: {}, flow EPE: {}'
                  .format(img_id_np, num_instances_np, image_np.shape, epe_np))

            # overlay masks
            for i in range(gt_boxes_np.shape[0]):
                label = trainId2label[gt_classes_np[i]]
                mask = np.expand_dims(gt_masks_np[i, :, :], 2)
                image_np += (0.5 * mask * np.array(label.color)).astype(np.uint8)
            # draw boxes
            im = Image.fromarray(image_np)
            imd = ImageDraw.Draw(im)
            for i in range(gt_boxes_np.shape[0]):
                label = trainId2label[gt_classes_np[i]]
                name = 'car' if gt_classes_np[i] == 1 else 'van'
                color = 'rgb({},{},{})'.format(*label.color)
                pos = gt_boxes_np[i, :]
                y0 = pos[0] * height
                x0 = pos[1] * width
                y1 = pos[2] * height
                x1 = pos[3] * width
                imd.rectangle([x0, y0, x1, y1], outline=color)
                imd.text(((x0 + x1) / 2, y1), name, fill=color)

            depth_im = Image.fromarray(np.squeeze(
                depth_np * 255 / 655.3).astype(np.uint8))
            flow_im = Image.fromarray(np.squeeze(
                flow_color_np * 255).astype(np.uint8))
            composed_flow_im = Image.fromarray(np.squeeze(
                composed_flow_color_np * 255).astype(np.uint8))
            flow_error_im = Image.fromarray(np.squeeze(
                flow_error_np * 255).astype(np.uint8))
            next_im = Image.fromarray(np.squeeze(example_np['next_image']))

            im.save(os.path.join(out_dir, str(img_id_np) + '_image1.png'))
            next_im.save(os.path.join(out_dir, str(img_id_np) + '_image2.png'))
            flow_im.save(os.path.join(out_dir, str(img_id_np) + '_flow.png'))
            depth_im.save(os.path.join(out_dir, str(img_id_np) + '_depth.png'))
            composed_flow_im.save(os.path.join(out_dir, str(img_id_np) + '_flow_from_motion.png'))
            #flow_error_im.save(os.path.join(out_dir, str(img_id_np) + '_flow_error.png'))
        sess.close()
