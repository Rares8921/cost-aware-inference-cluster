import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from typing import Optional
import structlog

logger = structlog.get_logger()


class ModelLoader:
    def __init__(self, model_name: str, model_version: str):
        self.model_name = model_name
        self.model_version = model_version
        self.model: Optional[torch.nn.Module] = None
        self.tokenizer = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def load(self):
        logger.info(
            "loading_model",
            model_name=self.model_name,
            device=self.device
        )

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            self.model_name
        )

        self.model.to(self.device)
        self.model.eval()

        logger.info(
            "model_loaded",
            model_name=self.model_name,
            device=self.device,
            parameters=sum(p.numel() for p in self.model.parameters())
        )

    def is_loaded(self) -> bool:
        return self.model is not None

    @torch.no_grad()
    def predict_batch(self, texts: list[str]) -> list[dict]:
        if not self.is_loaded():
            raise RuntimeError("Model not loaded")

        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt"
        )

        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        outputs = self.model(**inputs)
        logits = outputs.logits
        predictions = torch.softmax(logits, dim=-1)

        results = []
        for i, pred in enumerate(predictions):
            results.append({
                "probabilities": pred.cpu().tolist(),
                "predicted_class": int(torch.argmax(pred).item()),
                "confidence": float(torch.max(pred).item())
            })

        return results

    def warmup(self, num_warmup: int = 5):
        logger.info("warming_up_model", num_warmup=num_warmup)

        dummy_texts = [
            "This is a warmup text to initialize the model."
            for _ in range(self.model.config.batch_size if hasattr(self.model.config, 'batch_size') else 8)
        ]

        for _ in range(num_warmup):
            self.predict_batch(dummy_texts)

        logger.info("model_warmup_complete")
