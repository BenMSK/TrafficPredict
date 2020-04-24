# TrafficPredict
This repository is forked by (https://github.com/huang-xx/TrafficPredict).

The objective of this repo. is for studying 'trajectory prediction' field.

Original paper is [TrafficPredict: Trajectory Prediction for Heterogeneous Traffic-Agents](https://arxiv.org/abs/1811.02146) (AAAI), Oral, 2019.

## Comparison of results:
|   Methods  | Paper  ADE | This repo ADE | Paper  FDE | This repo FDE |
|:----------:|:----------:|:-------------:|:----------:|:-------------:|
| pedestrian |    0.091   |     0.088     |    0.150   |     0.132     |
|   bicycle  |    0.083   |     0.075     |    0.139   |     0.115     |
|   vehicle  |    0.080   |     0.090     |    0.131   |     0.153     |
|    total   |    0.085   |     0.084     |    0.141   |     0.133     |

## Requirements

* Python 3
* Seaborn (https://seaborn.pydata.org/)
* PyTorch (http://pytorch.org/)
* Numpy
* Matplotlib
* Scipy

## How to Run
* First `cd srnn`
* To train the model run `python train.py` (See the code to understand all the arguments that can be given to the command)
* To test the model run `python sample.py --epoch=n` where n is the epoch at which you want to load the saved model. (See the code to understand all the arguments that can be given to the command)
