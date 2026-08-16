import json
import random

from sentence_transformers import InputExample, SentenceTransformer, losses
from torch.utils.data import DataLoader

import wandb

MODEL_NAME = "BAAI/bge-m3"
OUTPUT_PATH = "finetuned_embeddings"
EPOCHS = 3
BATCH_SIZE = 16
WARMUP_STEPS = 100


# Build triplets (anchor, positive, hard_negative) from eval set
def build_training_examples(eval_file: str = "eval_set.json") -> list[InputExample]:
    with open(eval_file, "r") as f:
        eval_set = json.load(f)

    # Group questions by source
    by_source = {}
    for item in eval_set:
        source = item["source"]
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(item)

    examples = []
    for item in eval_set:
        anchor = item["question"]
        positive = item["correct_chunk_text"]

        # Hard negative: a chunk from the same source but different chunk index
        same_source = [
            x
            for x in by_source[item["source"]]
            if x["correct_chunk_index"] != item.get("correct_chunk_index", -1)
            and x.get("correct_chunk_text")
        ]
        if not same_source:
            continue

        hard_negative = random.choice(same_source)["correct_chunk_text"]

        examples.append(InputExample(texts=[anchor, positive, hard_negative]))

    print(f"Built {len(examples)} training triplets")
    return examples


def finetune(eval_file: str = "eval_set.json") -> None:
    examples = build_training_examples(eval_file)
    if not examples:
        print("No training examples found - check eval_set.json has correct_chunk_text field")
        return

    print(f"Loading {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)

    train_dataloader = DataLoader(examples, shuffle=True, batch_size=BATCH_SIZE)

    # TripletLoss: anchor closer to positive than negative by a margin
    train_loss = losses.TripletLoss(model=model)

    wandb.init(project="ragbase", name="embedding_finetune")
    wandb.config.update(
        {
            "model": MODEL_NAME,
            "epochs": EPOCHS,
            "batch_size": BATCH_SIZE,
            "loss": "TripletLoss",
            "training_examples": len(examples),
        }
    )

    print(f"Fine-tuning for {EPOCHS} epochs...")
    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=EPOCHS,
        warmup_steps=WARMUP_STEPS,
        output_path=OUTPUT_PATH,
        show_progress_bar=True,
    )

    print(f"Model saved to {OUTPUT_PATH}/")
    wandb.finish()


if __name__ == "__main__":
    finetune()
