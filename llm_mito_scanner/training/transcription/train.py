# AUTOGENERATED! DO NOT EDIT! File to edit: ../../../nbs/03 training.transcription.train.ipynb.

# %% auto 0
__all__ = ['DEVICE', 'UNK_IDX', 'PAD_IDX', 'BOS_IDX', 'EOS_IDX', 'text_transform', 'COLLATE_SIZE_LIM', 'set_vocab_idx',
           'PositionalEncoding', 'TokenEmbedding', 'Seq2SeqTransformer', 'sequential_transforms', 'tensor_transform',
           'set_text_transform', 'collate_fn', 'generate_square_subsequent_mask', 'create_mask', 'train_epoch',
           'evaluate', 'greedy_decode', 'translate']

# %% ../../../nbs/03 training.transcription.train.ipynb 1
from pathlib import Path
from torch import Tensor
import torch
import torch.nn as nn
from torch.nn import Transformer
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader
from torchtext.vocab import Vocab
import math
from timeit import default_timer as timer
from tqdm import tqdm

from llm_mito_scanner.data.download import load_config, \
    get_latest_assembly_path
from llm_mito_scanner.training.transcription.index import get_vocab, \
    TranscriptionDataset, index_training_sequence_files, \
    UNK_TOKEN, PAD_TOKEN, BOS_TOKEN, EOS_TOKEN, \
    tokenize

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# %% ../../../nbs/03 training.transcription.train.ipynb 6
UNK_IDX = None
PAD_IDX = None
BOS_IDX = None
EOS_IDX = None

def set_vocab_idx(vocab: Vocab):
    global UNK_IDX, PAD_IDX, BOS_IDX, EOS_IDX
    UNK_IDX = vocab[UNK_TOKEN]
    PAD_IDX = vocab[PAD_TOKEN]
    BOS_IDX = vocab[BOS_TOKEN]
    EOS_IDX = vocab[EOS_TOKEN]

# %% ../../../nbs/03 training.transcription.train.ipynb 9
# helper Module that adds positional encoding to the token embedding to introduce a notion of word order.
class PositionalEncoding(nn.Module):
    def __init__(self,
                 emb_size: int,
                 dropout: float,
                 maxlen: int = 5000):
        super(PositionalEncoding, self).__init__()
        den = torch.exp(- torch.arange(0, emb_size, 2)* math.log(10000) / emb_size)
        pos = torch.arange(0, maxlen).reshape(maxlen, 1)
        pos_embedding = torch.zeros((maxlen, emb_size))
        pos_embedding[:, 0::2] = torch.sin(pos * den)
        pos_embedding[:, 1::2] = torch.cos(pos * den)
        pos_embedding = pos_embedding.unsqueeze(-2)

        self.dropout = nn.Dropout(dropout)
        self.register_buffer('pos_embedding', pos_embedding)

    def forward(self, token_embedding: Tensor):
        return self.dropout(token_embedding + self.pos_embedding[:token_embedding.size(0), :])

# helper Module to convert tensor of input indices into corresponding tensor of token embeddings
class TokenEmbedding(nn.Module):
    def __init__(self, vocab_size: int, emb_size):
        super(TokenEmbedding, self).__init__()
        self.embedding = nn.Embedding(vocab_size, emb_size)
        self.emb_size = emb_size

    def forward(self, tokens: Tensor):
        return self.embedding(tokens.long()) * math.sqrt(self.emb_size)

# Seq2Seq Network
class Seq2SeqTransformer(nn.Module):
    def __init__(self,
                 num_encoder_layers: int,
                 num_decoder_layers: int,
                 emb_size: int,
                 nhead: int,
                 src_vocab_size: int,
                 tgt_vocab_size: int,
                 dim_feedforward: int = 512,
                 dropout: float = 0.1):
        super(Seq2SeqTransformer, self).__init__()
        self.transformer = Transformer(d_model=emb_size,
                                       nhead=nhead,
                                       num_encoder_layers=num_encoder_layers,
                                       num_decoder_layers=num_decoder_layers,
                                       dim_feedforward=dim_feedforward,
                                       dropout=dropout)
        self.generator = nn.Linear(emb_size, tgt_vocab_size)
        self.src_tok_emb = TokenEmbedding(src_vocab_size, emb_size)
        self.tgt_tok_emb = TokenEmbedding(tgt_vocab_size, emb_size)
        self.positional_encoding = PositionalEncoding(
            emb_size, dropout=dropout)

    def forward(self,
                src: Tensor,
                trg: Tensor,
                src_mask: Tensor,
                tgt_mask: Tensor,
                src_padding_mask: Tensor,
                tgt_padding_mask: Tensor,
                memory_key_padding_mask: Tensor):
        src_emb = self.positional_encoding(self.src_tok_emb(src))
        tgt_emb = self.positional_encoding(self.tgt_tok_emb(trg))
        outs = self.transformer(src_emb, tgt_emb, src_mask, tgt_mask, None,
                                src_padding_mask, tgt_padding_mask, memory_key_padding_mask)
        return self.generator(outs)

    def encode(self, src: Tensor, src_mask: Tensor):
        return self.transformer.encoder(self.positional_encoding(
                            self.src_tok_emb(src)), src_mask)

    def decode(self, tgt: Tensor, memory: Tensor, tgt_mask: Tensor):
        return self.transformer.decoder(self.positional_encoding(
                          self.tgt_tok_emb(tgt)), memory,
                          tgt_mask)

# %% ../../../nbs/03 training.transcription.train.ipynb 11
# helper function to club together sequential operations
def sequential_transforms(*transforms):
    def func(txt_input):
        for transform in transforms:
            txt_input = transform(txt_input)
        return txt_input
    return func

# function to add BOS/EOS and create tensor for input sequence indices
def tensor_transform(token_ids: list[int]):
    return torch.cat((torch.tensor([BOS_IDX]),
                      torch.tensor(token_ids),
                      torch.tensor([EOS_IDX])))

# %% ../../../nbs/03 training.transcription.train.ipynb 12
text_transform = None
def set_text_transform(
        text_vocab: Vocab
):
    global text_transform
    text_transform = sequential_transforms(
    tokenize, #Tokenization
    text_vocab, #Numericalization
    tensor_transform)

# %% ../../../nbs/03 training.transcription.train.ipynb 14
# function to collate data samples into batch tensors
def collate_fn(batch: list[tuple[str, str]]):
    src_batch, tgt_batch = [], []
    for src_sample, tgt_sample in batch:
        src_batch.append(text_transform(src_sample))
        tgt_batch.append(text_transform(tgt_sample))

    src_batch = pad_sequence(src_batch, padding_value=PAD_IDX)
    tgt_batch = pad_sequence(tgt_batch, padding_value=PAD_IDX)
    return src_batch, tgt_batch

# %% ../../../nbs/03 training.transcription.train.ipynb 20
COLLATE_SIZE_LIM = 500

# %% ../../../nbs/03 training.transcription.train.ipynb 28
def generate_square_subsequent_mask(sz):
    mask = (torch.triu(torch.ones((sz, sz), device=DEVICE)) == 1).transpose(0, 1)
    mask = mask.float().masked_fill(mask == 0, float('-inf')).masked_fill(mask == 1, float(0.0))
    return mask


def create_mask(src, tgt):
    src_seq_len = src.shape[0]
    tgt_seq_len = tgt.shape[0]

    tgt_mask = generate_square_subsequent_mask(tgt_seq_len)
    src_mask = torch.zeros((src_seq_len, src_seq_len), device=DEVICE).type(torch.bool)

    src_padding_mask = (src == PAD_IDX).transpose(0, 1)
    tgt_padding_mask = (tgt == PAD_IDX).transpose(0, 1)
    return src_mask, tgt_mask, src_padding_mask, tgt_padding_mask

# %% ../../../nbs/03 training.transcription.train.ipynb 37
def train_epoch(
        model, optimizer, loss_fn, 
        training_data_path: Path,
        sequences_data_path: Path,
        batch_size: int = 128,
        collate_size: int = 500,
        pbar_position: int = 1,
        chromosome: str | None = None):
    model.train()
    losses = 0
    counter = 0
    train_iter = TranscriptionDataset(training_data_path, sequences_data_path, train=True)
    if chromosome is not None:
        train_iter.filter_chromosome(chromosome)
    train_dataloader = DataLoader(train_iter, batch_size=batch_size, collate_fn=collate_fn)
    
    epoch_pbar = tqdm(total=len(train_iter), position=pbar_position, leave=False, ncols=80, desc="Transcripts")
    for src, tgt in train_dataloader:
        src = torch.split(src, collate_size)
        tgt = torch.split(tgt, collate_size)
        chunk_pbar = tqdm(total=len(src), position=pbar_position+1, leave=False, ncols=80, desc="Chunks")
        for src_chunk, tgt_chunk in zip(src, tgt):
            src_chunk = src_chunk.to(DEVICE)
            tgt_chunk = tgt_chunk.to(DEVICE)

            src_mask, tgt_mask, src_padding_mask, tgt_padding_mask = create_mask(src_chunk, tgt_chunk)

            chunk_logits = model(src_chunk, tgt_chunk, src_mask, tgt_mask, src_padding_mask, tgt_padding_mask, src_padding_mask)

            optimizer.zero_grad()

            loss = loss_fn(chunk_logits.reshape(-1, chunk_logits.shape[-1]), tgt_chunk.reshape(-1))
            loss.backward()

            optimizer.step()
            losses += loss.item()
            counter += 1
            chunk_pbar.update(1)

        chunk_pbar.close()
        epoch_pbar.update(1)

    epoch_pbar.close()

    return losses / counter


def evaluate(
        model, loss_fn, 
        training_data_path: Path,
        sequences_data_path: Path,
        batch_size: int = 128,
        collate_size: int = 500,
        pbar_position: int = 1,
        chromosome: str | None = None):
    model.eval()
    losses = 0
    counter = 0
    val_iter = TranscriptionDataset(training_data_path, sequences_data_path, train=False)
    if chromosome is not None:
        val_iter.filter_chromosome(chromosome)
    val_dataloader = DataLoader(val_iter, batch_size=batch_size, collate_fn=collate_fn)

    transcript_pbar = tqdm(total=len(val_iter), position=pbar_position, leave=False, ncols=80, desc="Transcripts")
    for src, tgt in val_dataloader:
        # Break these up into reasonable sizes for the GPU
        src = torch.split(src, collate_size)
        tgt = torch.split(tgt, collate_size)
        chunk_pbar = tqdm(total=len(src), position=pbar_position + 1, leave=False, ncols=80, desc="Chunks")
        for src_chunk, tgt_chunk in zip(src, tgt):
            src_chunk = src_chunk.to(DEVICE)
            tgt_chunk = tgt_chunk.to(DEVICE)

            src_mask, tgt_mask, src_padding_mask, tgt_padding_mask = create_mask(src_chunk, tgt_chunk)

            logits = model(src_chunk, tgt_chunk, src_mask, tgt_mask,src_padding_mask, tgt_padding_mask, src_padding_mask)

            loss = loss_fn(logits.reshape(-1, logits.shape[-1]), tgt_chunk.reshape(-1))
            losses += loss.item()
            counter += 1
            chunk_pbar.update(1)

        chunk_pbar.close()

        transcript_pbar.update(1)
        
    transcript_pbar.close()
    return losses / counter

# %% ../../../nbs/03 training.transcription.train.ipynb 39
# function to generate output sequence using greedy algorithm
def greedy_decode(model, src, src_mask, max_len, start_symbol):
    src = src.to(DEVICE)
    src_mask = src_mask.to(DEVICE)

    memory = model.encode(src, src_mask)
    ys = torch.ones(1, 1).fill_(start_symbol).type(torch.long).to(DEVICE)
    for i in range(max_len-1):
        memory = memory.to(DEVICE)
        tgt_mask = (generate_square_subsequent_mask(ys.size(0))
                    .type(torch.bool)).to(DEVICE)
        out = model.decode(ys, memory, tgt_mask)
        out = out.transpose(0, 1)
        prob = model.generator(out[:, -1])
        _, next_word = torch.max(prob, dim=1)
        next_word = next_word.item()

        ys = torch.cat([ys,
                        torch.ones(1, 1).type_as(src.data).fill_(next_word)], dim=0)
        if next_word == EOS_IDX:
            break
    return ys


# actual function to translate input sentence into target language
def translate(model: torch.nn.Module, vocab: Vocab, src_sentence: str):
    model.eval()
    src = text_transform(src_sentence).view(-1, 1)
    num_tokens = src.shape[0]
    src_mask = (torch.zeros(num_tokens, num_tokens)).type(torch.bool)
    tgt_tokens = greedy_decode(
        model,  src, src_mask, max_len=num_tokens + 5, start_symbol=BOS_IDX).flatten()
    return " ".join(vocab.lookup_tokens(list(tgt_tokens.cpu().numpy()))).replace("<bos>", "").replace("<eos>", "")
