"""Confident Learning — principled label-error detection (docs/07 §2).

Implements the **confident joint** of Northcutt, Jiang & Chuang, *Confident Learning:
Estimating Uncertainty in Dataset Labels* (JAIR 2021, arXiv 1911.00068) — the method that
surfaced ~100k label errors in ImageNet.

The algorithm, and why each piece matters:

1. **Out-of-sample predicted probabilities.** Probabilities must come from a model that did
   not see the example, or a flexible model simply memorizes its (possibly wrong) label and
   nothing looks like an error. We use K-fold cross-validation.
2. **Per-class thresholds.** The threshold for class *j* is the *mean self-confidence* of
   the examples labelled *j*. This is what makes CL robust to class imbalance and to
   miscalibrated models — a flat 0.5 cutoff would flag whole classes.
3. **The confident joint.** Count example *i* (labelled *y*) into cell ``(y, j)`` when its
   probability for *j* clears class *j*'s threshold. Off-diagonal mass is the evidence of
   label noise; an example whose confident label differs from its given label is a
   candidate error.
"""

from __future__ import annotations

import numpy as np

from bohrin._arrays import BoolArray, FloatArray, IntArray


def class_thresholds(labels: IntArray, probs: FloatArray) -> FloatArray:
    """Per-class threshold: the mean predicted self-confidence of that class's examples."""
    n_classes = probs.shape[1]
    out = np.ones(n_classes, dtype=np.float64)
    for k in range(n_classes):
        mask = labels == k
        if bool(mask.any()):
            out[k] = float(np.mean(probs[mask, k]))
    return out


def confident_joint(labels: IntArray, probs: FloatArray) -> IntArray:
    """The confident joint ``C[given_label, confident_label]`` (unnormalized counts)."""
    n_classes = probs.shape[1]
    thresholds = class_thresholds(labels, probs)
    joint = np.zeros((n_classes, n_classes), dtype=np.int64)
    for i in range(labels.shape[0]):
        row = probs[i]
        candidates = np.nonzero(row >= thresholds)[0]
        if candidates.size == 0:
            continue  # not confidently any class → contributes no evidence
        best = int(candidates[int(np.argmax(row[candidates]))])
        joint[int(labels[i]), best] += 1
    return joint


def label_error_mask(labels: IntArray, probs: FloatArray) -> BoolArray:
    """True where the confidently-predicted label disagrees with the given label."""
    thresholds = class_thresholds(labels, probs)
    mask = np.zeros(labels.shape[0], dtype=np.bool_)
    for i in range(labels.shape[0]):
        row = probs[i]
        candidates = np.nonzero(row >= thresholds)[0]
        if candidates.size == 0:
            continue
        best = int(candidates[int(np.argmax(row[candidates]))])
        mask[i] = best != int(labels[i])
    return mask


def self_confidence(labels: IntArray, probs: FloatArray) -> FloatArray:
    """Predicted probability assigned to each example's *given* label (lower = more suspect)."""
    idx = np.arange(labels.shape[0])
    out: FloatArray = probs[idx, labels].astype(np.float64)
    return out
