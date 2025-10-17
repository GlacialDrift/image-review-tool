import pandas as pd
from sklearn.metrics import cohen_kappa_score


def main():
    # Load your dataset
    df = pd.read_csv("decisions.csv")

    # Keep only QC images
    qc = df[df["QC"] == 1]

    # Pivot: one row per image_id, columns for each reviewer’s outcome
    qc_pivot = qc.pivot_table(
        index=["image id", "device_id"],   # keeps uniqueness
        columns="user",
        values="Loss of Coating Observed?",
        aggfunc='first'                    # ensures one value per reviewer
    )

    # Get all unique reviewer pairs
    reviewers = qc["user"].unique()
    pairs = [(r1, r2) for i, r1 in enumerate(reviewers) for r2 in reviewers[i+1:]]


    for r1, r2 in pairs:
        # Drop images where either reviewer didn’t review
        valid = qc_pivot[[r1, r2]].dropna()
        if len(valid) == 0:
            continue  # skip if no overlap between these two reviewers
        kappa = cohen_kappa_score(valid[r1], valid[r2])
        print(f"{r1} vs {r2}: Cohen's Kappa = {kappa:.3f} (n={len(valid)})")


if __name__ == "__main__":
    main()