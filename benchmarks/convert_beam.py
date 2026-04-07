#!/usr/bin/env python3
"""
Convert BEAM 100K dataset from HuggingFace parquet to JSON for the benchmark runner.

Dataset: https://huggingface.co/datasets/Mohammadta/BEAM
Paper: Tavakoli et al., "BEAM: Benchmark for Evaluating AI Memory" (2024)

Usage:
    pip install pandas pyarrow
    python benchmarks/convert_beam.py data/beam-100k.parquet data/beam-100k.json
"""

import ast
import json
import re
import sys


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "data/beam-100k.parquet"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "data/beam-100k.json"

    try:
        import pandas as pd
    except ImportError:
        print("ERROR: pandas and pyarrow are required for conversion.")
        print("  pip install pandas pyarrow")
        sys.exit(1)

    print(f"Reading {input_file}...")
    df = pd.read_parquet(input_file)
    print(f"  Rows: {len(df)}")

    conversations = []
    total_questions = 0

    for _, row in df.iterrows():
        conv_id = str(row.get("conversation_id", row.name))

        # Parse chat turns
        chat_raw = row.get("chat", "[]")
        if isinstance(chat_raw, str):
            try:
                chat = ast.literal_eval(chat_raw)
            except (ValueError, SyntaxError):
                chat = json.loads(chat_raw)
        else:
            chat = chat_raw

        # Extract user messages with time anchors
        user_messages = []
        for turn in chat:
            if isinstance(turn, dict):
                role = turn.get("role", "")
                content = turn.get("content", "")
                time_anchor = turn.get("time_anchor", "")
            elif isinstance(turn, (list, tuple)) and len(turn) >= 2:
                role, content = turn[0], turn[1]
                time_anchor = turn[2] if len(turn) > 2 else ""
            else:
                continue

            if role == "user" and content.strip():
                # Clean time anchor suffixes like "->->"
                if time_anchor:
                    time_anchor = re.sub(r"(->)+$", "", time_anchor).strip()
                user_messages.append({
                    "role": "user",
                    "content": content.strip(),
                    "time_anchor": time_anchor,
                })

        # Parse probing questions
        questions_raw = row.get("probing_questions", "[]")
        if isinstance(questions_raw, str):
            try:
                questions_parsed = ast.literal_eval(questions_raw)
            except (ValueError, SyntaxError):
                questions_parsed = json.loads(questions_raw)
        else:
            questions_parsed = questions_raw

        questions = []
        for q in questions_parsed:
            if isinstance(q, dict):
                rubric = q.get("rubric", [])
                if isinstance(rubric, str):
                    rubric = [rubric]
                questions.append({
                    "ability": q.get("ability", "unknown"),
                    "question": q.get("question", ""),
                    "reference_answer": q.get("reference_answer", ""),
                    "rubric": rubric,
                })

        total_questions += len(questions)

        conversations.append({
            "id": conv_id,
            "category": str(row.get("category", "unknown")),
            "title": str(row.get("title", "")),
            "user_messages": user_messages,
            "total_turns": len(user_messages),
            "questions": questions,
        })

    output = {
        "split": "100K",
        "num_conversations": len(conversations),
        "total_questions": total_questions,
        "conversations": conversations,
    }

    print(f"Writing {output_file}...")
    print(f"  Conversations: {len(conversations)}")
    print(f"  Total questions: {total_questions}")
    avg_msgs = sum(len(c["user_messages"]) for c in conversations) / max(len(conversations), 1)
    avg_qs = total_questions / max(len(conversations), 1)
    print(f"  Avg messages/conv: {avg_msgs:.0f}")
    print(f"  Avg questions/conv: {avg_qs:.1f}")

    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("Done.")


if __name__ == "__main__":
    main()
