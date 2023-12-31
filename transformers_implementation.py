# -*- coding: utf-8 -*-
"""Transformers_implementation.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1kDyaEZjLQGrmVJVHwFCCLprGvhe6xzpK
"""

# Attention is all you need paper - https://arxiv.org/pdf/1706.03762.pdf
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optimizer
import math
import numpy as np

class ScaledDotProductAtt(nn.Module):
  def __init__(self, dropout=0.1): #dropout as input for avoiding overfitting and improve generalization
    super(ScaledDotProductAtt, self).__init__()

    self.dropout = nn.Dropout(dropout)

  def forward(self, query, key, value, mask=None): #optional mask
    attScores = torch.matmul(query, key.transpose(-2, -1)) / np.sqrt(key.size(-1))
    if mask is not None: #Mask usually in the decoder
      attScores = attScores.masked_fill(mask == 0, -1e10) #Avoiding mask to be 0 to avoid inestabilities, low number instead

    attention = F.softmax(attScores, dim = -1)#last axis
    attention = self.dropout(attention) #dropping 30% of the scores
    return torch.matmul(attention, value), attention #added attention to get what the model is attending to

class MultiHeadAttention(nn.Module):
  def __init__(self, d_model, nhead, dropout=0.1):
    super(MultiHeadAttention, self).__init__()
    self.d_model = d_model # model dimension
    self.nhead = nhead # number of "heads"
    self.d_k = d_model // nhead # key dimension
    self.d_v = d_model // nhead # value dimension

    # Linearity for inputs
    self.linear_q = nn.Linear(d_model, d_model)
    self.linear_k = nn.Linear(d_model, d_model)
    self.linear_v = nn.Linear(d_model, d_model)

    self.scaledDotProductAttention = ScaledDotProductAtt(dropout)

    self.linearLayer = nn.Linear(d_model, d_model) # Linear layer at output
    self.dropout = nn.Dropout(dropout)

  def forward(self, query, key, value, mask=None, key_padding_mask=None):
    batchSize = query.size(0)

    query = self.linear_q(query).view(batchSize, -1, self.nhead, self.d_k).transpose(1,2)
    key = self.linear_q(key).view(batchSize, -1, self.nhead, self.d_k).transpose(1,2)
    value = self.linear_q(value).view(batchSize, -1, self.nhead, self.d_v).transpose(1,2)

    output, attScores = self.scaledDotProductAttention(query, key, value)

    outputConcat = output.transpose(1,2).contiguous().view(batchSize, -1, self.d_model)
    outputConcat = self.linearLayer(outputConcat)

    return self.dropout(outputConcat)

class PositionalEncoding(nn.Module):
  def __init__(self, d_model, dropout=0.1, maxLength=100):
    super(PositionalEncoding, self).__init__()

    self.dropout = nn.Dropout(dropout)
    pe = torch.zeros(maxLength, d_model)
    position = torch.arange(0, maxLength, dtype=torch.float).unsqueeze(1)
    divisionTerm = torch.exp(torch.arange(0, d_model, 2).float() * -(torch.log(torch.tensor(10000.0)) / d_model))

    pe[:, 0::2] = torch.sin(position * divisionTerm)
    pe[:, 1::2] = torch.cos(position * divisionTerm)

    pe = pe.unsqueeze(0).transpose(0,1)
    self.register_buffer('pe', pe)

  def forward(self, x):
    x = x + self.pe[:x.size(0), :]
    return self.dropout(x)

class FeedForward(nn.Module):
  def __init__(self, d_model, d_mlp=1024, dropout=0.1):
    super(FeedForward, self).__init__()
    self.linear_1 = nn.Linear(d_model, d_mlp)
    self.dropout = nn.Dropout(dropout)
    self.linear_2 = nn.Linear(d_mlp, d_model)

  def forward(self, x):
    x = self.linear_1(x)
    x = F.relu(x)
    x = self.dropout(x)
    x = self.linear_2(x)

    return x

class NormalizationLayer(nn.Module):
  def __init__(self, d_model, epsilon=1e-5):
    super(NormalizationLayer, self).__init__()
    self.gamma = nn.Parameter(torch.ones(d_model))
    self.beta = nn.Parameter(torch.zeros(d_model))
    self.epsilon = epsilon

  def forward(self, x):
    mean = x.mean(dim=1, keepdim=True)
    std = x.std(dim=-1, keepdim=True)

    x = (x - mean) / (std + self.epsilon)
    x = self.gamma * x + self.beta

    return x

class Encoder(nn.Module):
  def __init__(self, d_model, nhead, d_mlp, dropout=0.1):
    super(Encoder, self).__init__()

    self.multiHeadAttention = MultiHeadAttention(d_model, nhead, dropout)

    self.feedforward = FeedForward(d_model, d_mlp, dropout)

    self.normLayer1 = NormalizationLayer(d_model)
    self.normLayer2 = NormalizationLayer(d_model)

    self.dropout1 = nn.Dropout(dropout)
    self.dropout2 = nn.Dropout(dropout)

  def forward(self, x, src_mask=None, src_key_padding_mask=None, is_causal=False):
    x2 = self.multiHeadAttention(x, x, x, mask=src_mask, key_padding_mask=src_key_padding_mask)[0]
    x2 = self.normLayer1(x2)

    x = x + self.dropout1(x2)

    x2 = self.feedforward(x)
    x2 = self.normLayer2(x2)
    x = x + self.dropout2(x2)

    return x

class Decoder(nn.Module):
  def __init__(self, d_model, nhead, d_mlp, dropout=0.1):
    super(Decoder, self).__init__()

    self.maskedMultiHeadAttention = MultiHeadAttention(d_model, nhead, dropout)
    self.multiHeadAttention = MultiHeadAttention(d_model, nhead, dropout)

    self.feedforward = FeedForward(d_model, d_mlp, dropout)

    self.normLayer1 = NormalizationLayer(d_model)
    self.normLayer2 = NormalizationLayer(d_model)
    self.normLayer3 = NormalizationLayer(d_model)

    self.dropout1 = nn.Dropout(dropout)
    self.dropout2 = nn.Dropout(dropout)
    self.dropout3 = nn.Dropout(dropout)

  def forward(self, target, memory, tgt_mask=None, memory_mask=None, tgt_key_padding_mask=None, memory_key_padding_mask=None):
    target2 = self.maskedMultiHeadAttention(target, target, target, mask=tgt_mask, key_padding_mask=tgt_key_padding_mask)[0]
    target2 = self.normLayer1(target2)
    target = target + self.dropout1(target2)

    target2 = self.multiHeadAttention(target2, memory, memory, mask=memory_mask, key_padding_mask=memory_key_padding_mask)[0]
    target2 = self.normLayer2(target2)
    target = target + self.dropout2(target2)

    target2 = self.feedforward(target)
    target2 = self.normLayer3(target2)
    target = target + self.dropout3(target2)

    return target

class Transformer(nn.Module):
  def __init__(self, d_model, nhead, nEncoder, nDecoder, d_mlp, maxLength, nChar, padIndex, dropout=0.1):
    super(Transformer, self).__init__()
    self.d_model = d_model

    encoderLayer = Encoder(d_model, nhead, d_mlp, dropout)
    encoderNorm = NormalizationLayer(d_model)
    self.encoder = nn.TransformerEncoder(encoderLayer, nEncoder, encoderNorm)

    decoderLayer = Decoder(d_model, nhead, d_mlp, dropout)
    decoderNorm = NormalizationLayer(d_model)
    self.decoder = nn.TransformerDecoder(decoderLayer, nDecoder, decoderNorm)

    self.posEncoder = PositionalEncoding(d_model, dropout, maxLength)

    self.inputEmbed = nn.Embedding(nChar, d_model, padding_idx=padIndex)
    self.outputEmbed = nn.Embedding(nChar, d_model, padding_idx=padIndex)

    self.linear = nn.Linear(d_model, nChar)

  def forward(self, src, output, src_mask=None, outputMask=None, src_key_padding_mask=None, output_keyPaddingMask=None, memory_keyPaddingMask=None, isCausal=False):
    src = self.inputEmbed(src) * np.sqrt(self.d_model)
    src = self.posEncoder(src)
    encoderOutputs = self.encoder(src, mask=src_mask, src_key_padding_mask=src_key_padding_mask, is_causal=isCausal)

    output = self.outputEmbed(output) * np.sqrt(self.d_model)
    output = self.posEncoder(output)
    decoderOutputs = self.decoder(output, encoderOutputs, tgt_mask=outputMask, memory_mask=None, tgt_key_padding_mask=output_keyPaddingMask, memory_key_padding_mask=memory_keyPaddingMask)

    outputs = self.linear(decoderOutputs)
    return outputs

d_model = 512
nhead = 1
nEncoder = 1
nDecoder = 1
d_mlp = 1024
maxLength = 6
nChar = 26
padIndex = 0
dropout = 0.1

model = Transformer(d_model, nhead, nEncoder, nDecoder, d_mlp, maxLength, nChar, padIndex, dropout)

from torch.utils.data import Dataset, DataLoader

class ReverseDS(Dataset):
  def __init__(self, length=10000, seqLength=10):
    self.length = length
    self.seqLenght = seqLength
    self.vocab = list("abcdefghijklmnopqrstuvwxyz")
    self.vocabSize = len(self.vocab)
    self.charToIdx = {char: idx for idx, char in enumerate(self.vocab)}
    self.idxToChar = {idx: char for idx, char in enumerate(self.vocab)}

  def __len__(self):
    return self.length

  def __getitem__(self, index):
    sequence = torch.randint(high=self.vocabSize, size=(self.seqLenght,))
    return sequence, torch.flip(sequence, dims=[0])

dataset = ReverseDS(seqLength=maxLength)
dataloader = DataLoader(dataset, batch_size=5, shuffle=True)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = Transformer(d_model, nhead, nEncoder, nDecoder, d_mlp, maxLength, nChar, padIndex, dropout).to(device)

loss_func = nn.CrossEntropyLoss()
optimize = optimizer.Adam(model.parameters(), lr=0.0001)

def tokensToText(tokens, dataset):
  return ''.join(dataset.idxToChar[token.item()] for token in tokens)

inputs, targets = next(iter(dataloader))
print("input: ", tokensToText(inputs[4], dataset))
print("target: ", tokensToText(targets[4], dataset))

# Training Loop
nEpochs = 100

for epoch in range(nEpochs):
  for i, (input, target) in enumerate(dataloader):
    input = input.T.to(device)
    target = target.T.to(device)

    target_input = target[:-1, :]
    target_real = target[1:, :]

    output = model(input, target_real)

    lossFunc = loss_func(output.view(-1, nChar), target_real.reshape(-1))
    optimize.zero_grad()
    lossFunc.backward()
    optimize.step()

    if i % 100 == 0:
      print(f"Epoch: {epoch}, Iteration: {i}, Loss: {lossFunc.item()}")
      break

def outputToText(output, dataset):
  tokens = F.softmax(output, dim=-1)
  tokens = torch.argmax(tokens, dim=-1)
  text = ''.join(dataset.idxToChar[token.item()] for token in tokens)
  return text

inputs, targets = next(iter(dataloader))
index = 1
print("input: ", tokensToText(inputs[index], dataset))
print("target: ", tokensToText(targets[index], dataset))

input = inputs[index].T.to(device)
target = targets[index].T.to(device)
print(target)

output = model(input, target)
print(output)

print("input: ", tokensToText(inputs[index], dataset))
print("Prediction: ", outputToText(output[index], dataset))