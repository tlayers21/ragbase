import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function deriveSourceName(filename: string): string {
  return filename
    .replace(/\.[^/.]+$/, "")
    .toLowerCase()
    .replace(/\s+/g, "_");
}

// BGE-Reranker-v2-m3 emits raw, unbounded logits (roughly -10..+8), not
// probabilities — multiplying one by 100 yields nonsense like "-399% match".
// Sigmoid is the reranker's own normalization (FlagEmbedding's normalize=True),
// so it maps a score to the 0-1 relevance the UI is trying to show.
export function relevancePercent(score: number): number {
  return Math.round((1 / (1 + Math.exp(-score))) * 100);
}
