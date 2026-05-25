from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin, TransformerMixin
from sklearn.linear_model import LogisticRegression
from sklearn.utils.class_weight import compute_sample_weight


class TextSelector(BaseEstimator, TransformerMixin):
    """Pull the 'summary' field out of a list of dicts so the rest of the pipeline
    can work on plain strings.

    Input:  list of dicts with key 'summary' (str)
    Output: list of strings
    """
    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return [r["summary"] for r in X]


class WeightedLR(BaseEstimator, ClassifierMixin):
    """LogisticRegression wrapper that converts class_weight dict -> sample_weight at fit time.

    sklearn 1.8 has a regression where dict class_weight breaks inside
    cross_val_predict + predict_proba ("classes ... not in class_weight").
    Going through sample_weight bypasses the buggy validation path and works
    consistently across CV variants.
    """
    def __init__(self, class_weight=None, C=1.0, max_iter=2000, random_state=42):
        self.class_weight = class_weight
        self.C = C
        self.max_iter = max_iter
        self.random_state = random_state

    def fit(self, X, y, sample_weight=None):
        sw = None
        if isinstance(self.class_weight, dict):
            y_arr = np.asarray(y)
            classes_seen = np.unique(y_arr)
            if classes_seen.dtype.kind in "iu":
                # int-encoded by cross_val_predict; assume alphabetical class order
                key_translate = {0: "intangible", 1: "tangible"}
                weight_lookup = {c: self.class_weight.get(key_translate.get(int(c), c), 1.0)
                                 for c in classes_seen}
            else:
                weight_lookup = {c: self.class_weight.get(c, 1.0) for c in classes_seen}
            sw = np.array([weight_lookup[v] for v in y_arr], dtype=float)
        elif self.class_weight == "balanced":
            sw = compute_sample_weight("balanced", y)

        if sample_weight is not None:
            sw = sample_weight if sw is None else sw * sample_weight

        self._lr = LogisticRegression(C=self.C, max_iter=self.max_iter,
                                       random_state=self.random_state)
        self._lr.fit(X, y, sample_weight=sw)
        self.classes_ = self._lr.classes_
        self.coef_ = self._lr.coef_
        self.intercept_ = self._lr.intercept_
        return self

    def predict(self, X):
        return self._lr.predict(X)

    def predict_proba(self, X):
        return self._lr.predict_proba(X)

    def decision_function(self, X):
        return self._lr.decision_function(X)