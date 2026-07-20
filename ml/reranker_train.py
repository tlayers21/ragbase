import json
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from transformers import AutoTokenizer

import wandb
from config.logging import setup_logging
from config.paths import RERANKER_MODEL_PATH, TRAINING_PAIRS_PATH
from config.settings import WANDB_PROJECT
from retrieval.reranker import MODEL_NAME

logger = setup_logging(__name__)

BATCH_SIZE = 8
EPOCHS = 3
LEARNING_RATE = 2e-5
MAX_LENGTH = 256


class RerankerDataset(Dataset):
    """Pairwise dataset - each item is (question, positive_chunk, negative_chunk)."""

    def __init__(self, pairs, tokenizer):
        self.pairs = pairs
        self.tokenizer = tokenizer

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, idx):
        pair = self.pairs[idx]
        question = pair["question"]
        pos = pair["positive_chunk"]
        neg = pair["negative_chunk"]

        pos_encoded = self.tokenizer(
            question,
            pos,
            max_length=MAX_LENGTH,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        neg_encoded = self.tokenizer(
            question,
            neg,
            max_length=MAX_LENGTH,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

        return {
            "pos_input_ids": pos_encoded["input_ids"].squeeze(0),
            "pos_attention_mask": pos_encoded["attention_mask"].squeeze(0),
            "neg_input_ids": neg_encoded["input_ids"].squeeze(0),
            "neg_attention_mask": neg_encoded["attention_mask"].squeeze(0),
        }


def train(training_file: Path | None = None, run_name: str = "reranker_training") -> None:
    training_file = training_file or TRAINING_PAIRS_PATH

    with open(training_file, "r") as f:
        pairs = json.load(f)

    logger.info(f"Loaded {len(pairs)} training pairs")

    device = torch.device(
        "cuda"
        if torch.cuda.is_available()
        else "mps"
        if torch.backends.mps.is_available()
        else "cpu"
    )
    logger.info(f"Training on device: {device}")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    dataset = RerankerDataset(pairs, tokenizer)

    split = int(0.9 * len(dataset))
    train_set, val_set = torch.utils.data.random_split(dataset, [split, len(dataset) - split])
    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE)

    # TODO: RerankerModel was removed from retrieval/reranker.py when the reranker switched
    # to the pre-trained BAAI/bge-reranker-v2-m3. Re-implement here or remove this script.
    model = RerankerModel().to(device)  # noqa: F821
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.MarginRankingLoss(margin=0.5)

    wandb.init(project=WANDB_PROJECT, name=run_name)
    wandb.config.update(
        {
            "model": MODEL_NAME,
            "epochs": EPOCHS,
            "batch_size": BATCH_SIZE,
            "learning_rate": LEARNING_RATE,
            "training_pairs": len(pairs),
            "device": str(device),
        }
    )

    for epoch in range(EPOCHS):
        model.train()
        total_loss, correct, total = 0, 0, 0

        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            optimizer.zero_grad()

            pos_scores = model(batch["pos_input_ids"], batch["pos_attention_mask"]).float()
            neg_scores = model(batch["neg_input_ids"], batch["neg_attention_mask"]).float()

            target = torch.ones(pos_scores.size(0), device=device)
            loss = criterion(pos_scores, neg_scores, target)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            total_loss += loss.item()
            correct += (pos_scores > neg_scores).sum().item()
            total += pos_scores.size(0)

        train_loss = total_loss / len(train_loader)
        train_acc = correct / total

        model.eval()
        val_loss, val_correct, val_total = 0, 0, 0
        with torch.no_grad():
            for batch in val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                pos_scores = model(batch["pos_input_ids"], batch["pos_attention_mask"])
                neg_scores = model(batch["neg_input_ids"], batch["neg_attention_mask"])
                target = torch.ones(pos_scores.size(0), device=device)
                loss = criterion(pos_scores, neg_scores, target)
                val_loss += loss.item()
                val_correct += (pos_scores > neg_scores).sum().item()
                val_total += pos_scores.size(0)

        val_loss_avg = val_loss / len(val_loader)
        val_acc = val_correct / val_total

        logger.info(
            f"Epoch {epoch + 1}/{EPOCHS} — train loss: {train_loss:.4f} acc: {train_acc:.3f} "
            f"val loss: {val_loss_avg:.4f} acc: {val_acc:.3f}"
        )
        wandb.log(
            {
                "epoch": epoch + 1,
                "train_loss": train_loss,
                "train_accuracy": train_acc,
                "val_loss": val_loss_avg,
                "val_accuracy": val_acc,
            }
        )

    RERANKER_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), RERANKER_MODEL_PATH)
    logger.info(f"Model saved to {RERANKER_MODEL_PATH}")
    wandb.finish()


if __name__ == "__main__":
    import sys

    run_name = sys.argv[1] if len(sys.argv) > 1 else "reranker_training"
    train(run_name=run_name)
