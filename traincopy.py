import os
import math
import argparse
import random
import logging

import paddle 
import paddle.distributed as dist
from paddle.distributed import fleet
from data.data_sampler import DistIterSampler

import config.config as option
from utils import util
from data import create_dataloader, create_dataset
from models import create_model
import numpy as np


def init_dist(backend='nccl', **kwargs):
    """initialization for distributed training"""
    rank = paddle.distributed.ParallelEnv().rank
    paddle.device.set_device(f"gpu:{rank}")
    strategy = fleet.DistributedStrategy()
    fleet.init(is_collective=True, strategy=strategy)


def main():
    #### options
    parser = argparse.ArgumentParser()
    parser.add_argument('-opt', type=str, default=r'config/train/train_ClassSR_RCAN.yml',help='Path to option YAML file.')
    parser.add_argument('--launcher', choices=['none', 'fleet'], default='none',
                        help='job launcher')
    parser.add_argument('--local_rank', type=int, default=0)
    args = parser.parse_args()
    opt = option.parse(args.opt, is_train=True)
    opt_net = opt['network_G']
    which_model = opt_net['which_model_G']

    #### distributed training settings
    if args.launcher == 'none':  # disabled distributed training
        opt['dist'] = False
        rank = -1
        print('Disabled distributed training.')
    else:
        opt['dist'] = True
        rank = paddle.distributed.ParallelEnv().rank
        world_size = paddle.distributed.ParallelEnv().world_size
        init_dist()

    #### loading resume state if exists
    if opt['path'].get('resume_state', None):
        # distributed resuming: all load into default GPU
        device_id = paddle.distributed.ParallelEnv().device_id
        resume_state = paddle.load(opt['path']['resume_state'])
        option.check_resume(opt, resume_state['iter'])  # check resume options
    else:
        resume_state = None

    #### mkdir and loggers
    if rank <= 0:  # normal training (rank -1) OR distributed training (rank 0)
        # if resume_state is None:
        util.mkdir_and_rename(
                opt['path']['experiments_root'])  # rename experiment folder if exists
        util.mkdirs((path for key, path in opt['path'].items() if not key == 'experiments_root'
                         and 'pretrain_model' not in key and 'resume' not in key))

        # config loggers. Before it, the log will not work
        util.setup_logger('base', opt['path']['log'], 'train_' + opt['name'], level=logging.INFO,
                          screen=True, tofile=True)
        logger = logging.getLogger('base')
        logger.info(option.dict2str(opt))
        # tensorboard logger
        if opt['use_tb_logger'] and 'debug' not in opt['name']:
            from visualdl import LogWriter
            tb_logger = LogWriter(logdir='../tb_logger/' + opt['name'])
    else:
        util.setup_logger('base', opt['path']['log'], 'train', level=logging.INFO, screen=True)
        logger = logging.getLogger('base')

    # convert to NoneDict, which returns None for missing keys
    opt = option.dict_to_nonedict(opt)

    #### random seed
    seed = opt['train']['manual_seed']
    if seed is None:
        seed = random.randint(1, 10000)
    if rank <= 0:
        logger.info('Random seed: {}'.format(seed))
    util.set_random_seed(seed)

    #### create train and val dataloader
    dataset_ratio = 1  # enlarge the size of each epoch
    for phase, dataset_opt in opt['datasets'].items():
        if phase == 'train':
            train_set = create_dataset(dataset_opt)
            train_size = int(math.ceil(len(train_set) / dataset_opt['batch_size']))
            total_iters = int(opt['train']['niter'])
            total_epochs = int(math.ceil(total_iters / train_size))
            if opt['dist']:
                train_sampler = DistIterSampler(train_set, world_size, rank, dataset_ratio)
                # train_sampler = paddle.io.DistributedBatchSampler(
                #     train_set, batch_size=dataset_opt['batch_size'], shuffle=True, drop_last=True)
                total_epochs = int(math.ceil(total_iters / (train_size * dataset_ratio)))
            else:
                train_sampler = None
            train_loader = create_dataloader(train_set, dataset_opt, opt, train_sampler)
            if rank <= 0:
                logger.info('Number of train images: {:,d}, iters: {:,d}'.format(
                    len(train_set), train_size))
                logger.info('Total epochs needed: {:d} for iters {:,d}'.format(
                    total_epochs, total_iters))
        elif phase == 'val':
            val_set = create_dataset(dataset_opt)
            val_loader = create_dataloader(val_set, dataset_opt, opt, None)
            if rank <= 0:
                logger.info('Number of val images in [{:s}]: {:d}'.format(
                    dataset_opt['name'], len(val_set)))
        else:
            raise NotImplementedError('Phase [{:s}] is not recognized.'.format(phase))
    assert train_loader is not None

    #### create model
    model = create_model(opt)

    #### resume training
    if resume_state:
        logger.info('Resuming training from epoch: {}, iter: {}.'.format(
            resume_state['epoch'], resume_state['iter']))

        start_epoch = resume_state['epoch']
        current_step = resume_state['iter']
        model.resume_training(resume_state)  # handle optimizers and schedulers
    else:
        current_step = 0
        start_epoch = 0

    #### training
    logger.info('Start training from epoch: {:d}, iter: {:d}'.format(start_epoch, current_step))
    for epoch in range(start_epoch, total_epochs + 1):
        if opt['dist']:
            train_sampler.set_epoch(epoch)
        for _, train_data in enumerate(train_loader):
            current_step += 1
            if current_step > total_iters:
                break
            #### update learning rate
            model.update_learning_rate(current_step, warmup_iter=opt['train']['warmup_iter'])

            #### training
            #print(train_data)
            model.feed_data(train_data)
            model.optimize_parameters(current_step)

            #### log
            if current_step % opt['logger']['print_freq'] == 0:
                logs = model.get_current_log()
                message = '[epoch:{:3d}, iter:{:8,d}, lr:('.format(epoch, current_step)
                for v in model.get_current_learning_rate():
                    message += '{:.3e},'.format(v)
                message += ')] '
                for k, v in logs.items():
                    message += '{:s}: {:.4e} '.format(k, v)
                    # tensorboard logger
                    if opt['use_tb_logger'] and 'debug' not in opt['name']:
                        if rank <= 0:
                            tb_logger.add_scalar(k, v, current_step)
                if rank <= 0:
                    logger.info(message)
            ### validation
            if rank <= 0 and opt['datasets'].get('val', None) and current_step % opt['train']['val_freq'] == 0:
                if opt['model'] in ['vsr'] and rank <= 0:    # video restoration validation
                    if opt['dist']:
                        # multi-GPU testing
                        psnr_rlt = {}  # with border and center frames
                        if rank == 0:
                            pbar = util.ProgressBar(len(val_set))
                        for idx in range(rank, len(val_set), world_size):
                            val_data = val_set[idx]
                            val_data['LQs'].unsqueeze_(0)
                            val_data['GT'].unsqueeze_(0)
                            folder = val_data['folder']
                            idx_d, max_idx = val_data['idx'].split('/')
                            idx_d, max_idx = int(idx_d), int(max_idx)
                            if psnr_rlt.get(folder, None) is None:
                                psnr_rlt[folder] = paddle.zeros(max_idx, dtype=paddle.float32,
                                                               device='cuda')
                            model.feed_data(val_data)
                            model.test()
                            visuals = model.get_current_visuals()
                            rlt_img = util.tensor2img(visuals['rlt'])  # uint8
                            gt_img = util.tensor2img(visuals['GT'])  # uint8
                            # calculate PSNR
                            psnr_rlt[folder][idx_d] = util.calculate_psnr(rlt_img, gt_img)

                            if rank == 0:
                                for _ in range(world_size):
                                    pbar.update('Test {} - {}/{}'.format(folder, idx_d, max_idx))
                        # # collect data
                        for _, v in psnr_rlt.items():
                            dist.reduce(v, 0)
                        dist.barrier()

                        if rank == 0:
                            psnr_rlt_avg = {}
                            psnr_total_avg = 0.
                            for k, v in psnr_rlt.items():
                                psnr_rlt_avg[k] = paddle.mean(v).cpu().item()
                                psnr_total_avg += psnr_rlt_avg[k]
                            psnr_total_avg /= len(psnr_rlt)
                            log_s = '# Validation # PSNR: {:.4e}:'.format(psnr_total_avg)
                            for k, v in psnr_rlt_avg.items():
                                log_s += ' {}: {:.4e}'.format(k, v)
                            logger.info(log_s)
                            if opt['use_tb_logger'] and 'debug' not in opt['name']:
                                tb_logger.add_scalar('psnr_avg', psnr_total_avg, current_step)
                                for k, v in psnr_rlt_avg.items():
                                    tb_logger.add_scalar(k, v, current_step)
                    else:# image restoration validation
                        pbar = util.ProgressBar(len(val_loader))
                        psnr_rlt = {}  # with border and center frames
                        psnr_rlt_avg = {}
                        psnr_total_avg = 0.
                        for val_data in val_loader:
                            folder = val_data['folder'][0]
                            idx_d = val_data['idx'].item()
                            # border = val_data['border'].item()
                            if psnr_rlt.get(folder, None) is None:
                                psnr_rlt[folder] = []

                            model.feed_data(val_data)
                            model.test()
                            visuals = model.get_current_visuals()
                            rlt_img = util.tensor2img(visuals['rlt'])  # uint8
                            gt_img = util.tensor2img(visuals['GT'])  # uint8

                            # calculate PSNR
                            psnr = util.calculate_psnr(rlt_img, gt_img)
                            psnr_rlt[folder].append(psnr)
                            pbar.update('Test {} - {}'.format(folder, idx_d))
                        for k, v in psnr_rlt.items():
                            psnr_rlt_avg[k] = sum(v) / len(v)
                            psnr_total_avg += psnr_rlt_avg[k]
                        psnr_total_avg /= len(psnr_rlt)
                        log_s = '# Validation # PSNR: {:.4e}:'.format(psnr_total_avg)
                        for k, v in psnr_rlt_avg.items():
                            log_s += ' {}: {:.4e}'.format(k, v)
                        logger.info(log_s)
                        if opt['use_tb_logger'] and 'debug' not in opt['name']:
                            tb_logger.add_scalar('psnr_avg', psnr_total_avg, current_step)
                            for k, v in psnr_rlt_avg.items():
                                tb_logger.add_scalar(k, v, current_step)
                else:
                    # does not support multi-GPU validation
                    pbar = util.ProgressBar(len(val_loader))
                    avg_psnr = 0.
                    idx = 0
                    num_ress = [0, 0,0]
                    psnr_ress=[0, 0,0]
                    for val_data in val_loader:
                        idx += 1
                        img_name = os.path.splitext(os.path.basename(val_data['LQ_path'][0]))[0]
                        img_dir = os.path.join(opt['path']['val_images'], img_name)
                        util.mkdir(img_dir)
                        model.feed_data(val_data)
                        model.test()
                        visuals = model.get_current_visuals()
                        sr_img = visuals['rlt'] # uint8
                        gt_img = visuals['GT'] # uint8
                        num_res = visuals['num_res']
                        psnr_res=visuals['psnr_res']
                        num_ress[0] += num_res[0]
                        num_ress[1] += num_res[1]
                        num_ress[2] += num_res[2]
                        psnr_ress[0] += psnr_res[0]
                        psnr_ress[1] += psnr_res[1]
                        psnr_ress[2] += psnr_res[2]
                        # Save SR images for reference
                        save_img_path = os.path.join(img_dir,
                                                     '{:s}_{:d}.png'.format(img_name, current_step))
                        util.save_img(sr_img, save_img_path)

                    if num_ress[1]==0:
                        num_ress[1]=1
                    if num_ress[2]==0:
                        num_ress[2]=1
                    avg_psnr /= idx
                    # log
                    logger.info('# Validation # PSNR: {:.4e}'.format(avg_psnr))
                    logger.info('# Validation # FLOPs: {:.4e}'.format(flops))
                    logger.info('# Validation # Percent: {:.4e}'.format(percent))
                    logger.info('# Validation # TYPE num: {0} {1} {2} '.format(num_ress[0], num_ress[1],num_ress[2]))
                    logger.info('# Validation # PSNR Class: {0} {1} {2}'.format(psnr_ress[0]/num_ress[0],psnr_ress[1]/num_ress[1],psnr_ress[2]/num_ress[2]))
                    # tensorboard logger
                    if rank <= 0 and opt['use_tb_logger'] and 'debug' not in opt['name']:
                        tb_logger.add_scalar('PSNR', avg_psnr, current_step)
                        tb_logger.add_scalar('FLOPs', flops, current_step)


    if rank <= 0:
        logger.info('Saving the final model.')
        model.save('latest')
        logger.info('End of training.')
        tb_logger.close()


if __name__ == '__main__':
    main()
