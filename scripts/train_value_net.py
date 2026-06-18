#!/usr/bin/env python3
"""Train ValueNet on random self-play JSONL logs."""

import json
import os
import sys

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.value_net import ValueNet


LOG_PATH = "logs/self_play_10k.jsonl"
MODEL_PATH = "models/value_net_best.pt"
FEATURE_KEYS = [
    "prize_diff",
    "my_prize",
    "opp_prize",
    "my_active_hp_ratio",
    "opp_active_hp_ratio",
    "my_bench_count",
    "opp_bench_count",
    "my_hand_count",
    "opp_hand_count",
    "turn",
]


def choose_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_dataset(path):
    xs = []
    ys = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            features = row["features"]
            xs.append([float(features[k]) for k in FEATURE_KEYS])
            ys.append(1.0 if row["player"] == row["result"] else 0.0)
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32)


def make_batches(x, y, batch_size, shuffle, rng):
    indices = np.arange(len(x))
    if shuffle:
        rng.shuffle(indices)
    for start in range(0, len(indices), batch_size):
        idx = indices[start:start + batch_size]
        yield x[idx], y[idx]


def evaluate(model, x, y, criterion, batch_size, device):
    model.eval()
    total_loss = 0.0
    total_count = 0
    preds = []
    with torch.no_grad():
        for xb, yb in make_batches(x, y, batch_size, False, np.random.default_rng(0)):
            xt = torch.from_numpy(xb).to(device)
            yt = torch.from_numpy(yb).to(device)
            out = model(xt)
            loss = criterion(out, yt)
            total_loss += float(loss.item()) * len(xb)
            total_count += len(xb)
            preds.append(out.detach().cpu().numpy())
    pred = np.concatenate(preds)
    return total_loss / max(total_count, 1), pred


def main():
    os.makedirs("models", exist_ok=True)
    device = choose_device()
    print(f"DEVICE: {device}")

    x, y = load_dataset(LOG_PATH)
    rng = np.random.default_rng(42)
    indices = np.arange(len(x))
    rng.shuffle(indices)
    split = int(len(indices) * 0.8)
    train_idx = indices[:split]
    valid_idx = indices[split:]

    x_train = x[train_idx]
    y_train = y[train_idx]
    x_valid = x[valid_idx]
    y_valid = y[valid_idx]

    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std[std < 1e-6] = 1.0
    x_train = (x_train - mean) / std
    x_valid = (x_valid - mean) / std

    model = ValueNet(input_dim=x_train.shape[1]).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.BCELoss()

    batch_size = 2048
    epochs = 20
    patience = 5
    best_loss = float("inf")
    best_epoch = 0
    epochs_trained = 0

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        train_count = 0
        epoch_rng = np.random.default_rng(42 + epoch)
        for xb, yb in make_batches(x_train, y_train, batch_size, True, epoch_rng):
            xt = torch.from_numpy(xb).to(device)
            yt = torch.from_numpy(yb).to(device)
            optimizer.zero_grad(set_to_none=True)
            out = model(xt)
            loss = criterion(out, yt)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item()) * len(xb)
            train_count += len(xb)

        train_loss /= max(train_count, 1)
        valid_loss, _ = evaluate(model, x_valid, y_valid, criterion, batch_size, device)
        epochs_trained = epoch

        improved = valid_loss < best_loss - 1e-6
        if improved:
            best_loss = valid_loss
            best_epoch = epoch
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "input_dim": x_train.shape[1],
                    "feature_keys": FEATURE_KEYS,
                    "mean": mean.astype(np.float32),
                    "std": std.astype(np.float32),
                    "valid_loss": best_loss,
                    "epoch": epoch,
                },
                MODEL_PATH,
            )

        print(
            f"Epoch {epoch:02d}/{epochs} | train_loss: {train_loss:.4f} | "
            f"valid_loss: {valid_loss:.4f} | best: {'*' if improved else ''}",
            flush=True,
        )

        if epoch - best_epoch >= patience:
            break

    checkpoint = torch.load(MODEL_PATH, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    valid_loss, valid_pred = evaluate(model, x_valid, y_valid, criterion, batch_size, device)
    valid_acc = ((valid_pred >= 0.5) == (y_valid >= 0.5)).mean()
    valid_auc = roc_auc_score(y_valid, valid_pred)

    print("TRAIN_DONE: OK")
    print(f"MODEL_PATH: {MODEL_PATH}")
    print(f"VALID_ACCURACY: {valid_acc * 100:.2f}%")
    print(f"VALID_AUC: {valid_auc:.3f}")
    print(f"EPOCHS_TRAINED: {epochs_trained}")


if __name__ == "__main__":
    main()
