""":class:`OwlV2Detector` adapter over the worker's already-loaded OWLv2.

The overlay pass's crop picker
(:func:`heimdex_media_pipelines.product_enum.enumerate_products_overlay`)
needs an OWLv2 zero-shot detector that conforms to the pipelines
:class:`heimdex_media_pipelines.product_enum.OwlV2Detector` protocol::

    detect(frame_bgr, queries) -> [{'bbox': (x1, y1, x2, y2), 'confidence': float}, ...]

with bbox coordinates **normalised to [0, 1]**.

The worker already loads OWLv2 once at boot (``worker.py::_load_owlv2``)
and hands the processor + ONNX session + device to
:class:`src.openai_vlm.OpenAIVlmClient` for the vision pass. This
adapter shares the SAME loaded objects — no second model load, no extra
VRAM — and only differs in two ways from the vision path's OWLv2 use:

* the query list comes from the overlay pipeline (``queries`` arg),
  not the vision-path ``DEFAULT_OWLV2_QUERIES``;
* the output is normalised xyxy (what the overlay picker scores on),
  not original-pixel xywh (what the vision path's labeler crops on).

Pure inference plumbing — the heavy work (forward pass, post-process)
is the transformers ``Owlv2Processor`` + the injected ONNX session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np
    import onnxruntime as ort
    import torch
    from PIL import Image
    from transformers import Owlv2Processor


class WorkerOwlV2Detector:
    """Conforms to
    :class:`heimdex_media_pipelines.product_enum.OwlV2Detector`.

    Construct once at worker boot from the same OWLv2 objects passed to
    :class:`OpenAIVlmClient`. Stateless per call.
    """

    def __init__(
        self,
        *,
        processor: "Owlv2Processor",
        session: "ort.InferenceSession",
        device: "torch.device",
        threshold: float = 0.13,
        max_image_side: int = 960,
    ) -> None:
        self._processor = processor
        self._session = session
        self._device = device
        # Lower default than the vision path's 0.45 — the overlay picker
        # does its own composite scoring + position gating downstream, so
        # we want OWLv2 to surface more candidate crops here and let the
        # picker choose. Mirrors the API image_picker's 0.13 cutoff.
        self.threshold = threshold
        self.max_image_side = max_image_side

    def detect(
        self,
        frame_bgr: "np.ndarray",
        queries: list[str],
    ) -> list[dict[str, Any]]:
        """Run OWLv2 on one BGR frame for ``queries``.

        Returns one ``{'bbox': (x1, y1, x2, y2), 'confidence': float}``
        per detection, bbox normalised to ``[0, 1]`` relative to the
        input frame.
        """
        if not queries:
            return []

        import numpy as np
        import torch
        from PIL import Image

        # cv2 BGR uint8 -> PIL RGB. The processor + ONNX session were
        # calibrated on RGB (Owlv2Processor) so the channel order matters.
        rgb = frame_bgr[:, :, ::-1]
        pil = Image.fromarray(np.ascontiguousarray(rgb)).convert("RGB")

        orig_w, orig_h = pil.size
        sent = self._resize(pil)
        sent_w, sent_h = sent.size

        inputs = self._processor(
            text=[queries], images=sent, return_tensors="np",
        )
        ort_inputs = {
            "input_ids": inputs["input_ids"].astype(np.int64),
            "attention_mask": inputs["attention_mask"].astype(np.int64),
            "pixel_values": inputs["pixel_values"].astype(np.float32),
        }
        logits_np, pred_boxes_np = self._session.run(
            ["logits", "pred_boxes"], ort_inputs,
        )

        class _Out:
            pass

        outputs = _Out()
        outputs.logits = torch.from_numpy(logits_np)
        outputs.pred_boxes = torch.from_numpy(pred_boxes_np)
        target_sizes = torch.tensor([[sent_h, sent_w]])
        results = self._processor.post_process_grounded_object_detection(
            outputs=outputs,
            target_sizes=target_sizes,
            threshold=self.threshold,
        )[0]

        scores = results["scores"].detach().cpu().tolist()
        boxes = results["boxes"].detach().cpu().tolist()

        # Boxes are in ``sent`` pixel coords; normalise by the sent size
        # (the same [0, 1] frame the original maps to under uniform
        # resize) and clamp.
        out: list[dict[str, Any]] = []
        for score, box in zip(scores, boxes, strict=False):
            x1, y1, x2, y2 = box
            nx1 = max(0.0, min(1.0, x1 / sent_w))
            ny1 = max(0.0, min(1.0, y1 / sent_h))
            nx2 = max(0.0, min(1.0, x2 / sent_w))
            ny2 = max(0.0, min(1.0, y2 / sent_h))
            if nx2 <= nx1 or ny2 <= ny1:
                continue
            out.append(
                {"bbox": (nx1, ny1, nx2, ny2), "confidence": float(score)}
            )
        return out

    def _resize(self, image: "Image.Image") -> "Image.Image":
        """Downscale so the long edge <= ``max_image_side`` (mirrors
        ``OpenAIVlmClient._resize_for_owlv2``)."""
        from PIL import Image as PILImage

        w, h = image.size
        long_side = max(w, h)
        if long_side <= self.max_image_side:
            return image
        scale = self.max_image_side / long_side
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        return image.resize((new_w, new_h), resample=PILImage.LANCZOS)
