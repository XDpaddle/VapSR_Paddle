# VapSR_paddle

Paddle 复现版本

## 数据集

分类之后训练集用于训练SR模块
https://aistudio.baidu.com/aistudio/datasetdetail/106261

## 训练模型
链接：https://pan.baidu.com/s/1jf0UKI_wf7yRhwdA4AU5Kw 
提取码：u9lr
## 训练步骤
### train sr
```bash
python train.py -opt config/train/train_vapsr_x2.yml
```

## 测试步骤
```bash
python test.py -opt config/test/test_varsp_x2.yml
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


