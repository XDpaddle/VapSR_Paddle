# VapSR_paddle

Paddle 复现版本

## 数据集

分类之后训练集用于训练SR模块
https://aistudio.baidu.com/aistudio/datasetdetail/106261
## aistudio
脚本任务地址: https://aistudio.baidu.com/aistudio/clusterprojectdetail/2356381
## 训练模型
链接：https://pan.baidu.com/s/1jf0UKI_wf7yRhwdA4AU5Kw 
提取码：u9lr
## 训练步骤
### train sr
```bash
python train.py -opt config/train/train_vapsr_x2.yml
```
### train ClassSR
```bash
python train_ClassSR.py -opt config/train/train_ClassSR_RCAN.yml
```
多卡仅需
```bash
python -m paddle.distributed.launch train.py --launcher fleet -opt config_file_path
python -m paddle.distributed.launch train_ClassSR.py --launcher fleet -opt config_file_path
```
## 测试步骤
```bash
python test.py -opt config/test/test_varsp_x2.yml
```
```bash
python test_ClassSR.py -opt config/test/test_ClassSR_RCAN.yml
```
## 实验结果
### 训练结果
<p float="left">
    <img src="figs/class_loss.png" width="300"/><img src="figs/FLOPs.png" width="300"/>
</p>
<p float="left">
    <img src="figs/Percent.png" width="300"/><img src="figs/PSNR.png" width="300"/>
</p>

### 超分图片

<p float="left">
    <img src="figs/1201HR.png" width="300"/><img src="figs/1201LR.png" width="300"/><img src="figs/1201SR.png" width="300"/>
</p>

## 复现指标

|      | PSNR  | FLOPs | Percent |
| ---- | ----- | ------------------ | ------------ |
| 论文  | 26.39 | 21.22     | 65% |
| Paddle  | 26.35 | 21.37     | 65.5% |
## 参考资料

- [Xiangtaokong/ClassSR](https://github.com/Xiangtaokong/ClassSR)
