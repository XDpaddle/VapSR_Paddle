# VapSR_paddle

Efficient Image Super Resolution using Vast Receptive Field Attention    Paddle 复现版本

论文链接 https://arxiv.org/abs/2210.05960

## 训练模型
trans_weights/
## 训练步骤
### train sr
```bash
python train.py -opt config/train/train_vapsr_x2.yml
```
## 测试步骤
```bash
python test.py -opt config/test/test_varsp_x2.yml
```
## 数据集
```bash
DIV2K
https://data.vision.ee.ethz.ch/cvl/DIV2K/
Set5
https://drive.google.com/drive/folders/1pRmhEmmY-tPF7uH8DuVthfHoApZWJ1QU
```
