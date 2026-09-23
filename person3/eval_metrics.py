import numpy as np

def iou(pred_mask, true_mask):
    pred = pred_mask.astype(bool)
    true = true_mask.astype(bool)
    intersection = np.logical_and(pred, true).sum()
    union = np.logical_or(pred, true).sum()
    return intersection / union if union > 0 else 0.0

def precision_recall_f1(pred_mask, true_mask):
    pred = pred_mask.astype(bool)
    true = true_mask.astype(bool)
    tp = np.logical_and(pred, true).sum()
    fp = np.logical_and(pred, ~true).sum()
    fn = np.logical_and(~pred, true).sum()
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1

if __name__ == "__main__":
    # quick sanity test with fake data
    true_mask = np.array([[1, 0], [0, 1]])
    pred_mask = np.array([[1, 0], [1, 1]])
    print("IoU:", iou(pred_mask, true_mask))
    print("P/R/F1:", precision_recall_f1(pred_mask, true_mask))