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
