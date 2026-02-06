import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime
import os
import json
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from datasets import Dataset
from llama_index.core import Settings

from core_intelligence.schemas.models import EvaluationResult, QueryResponse
from shared_utils.logging_utils import ContextualLogger
from shared_utils.constants import LogScope

logger = ContextualLogger(scope=LogScope.MONITORING)

class EvaluationEngine:
    """Evaluation engine using Ragas metrics."""

    def __init__(self, llm_provider=None, metrics_path: str = "data/metrics/historical_metrics.json"):
        self.llm_provider = llm_provider
        self.metrics_path = metrics_path
        os.makedirs(os.path.dirname(self.metrics_path), exist_ok=True)
        
        # Initialize metrics if not exists
        if not os.path.exists(self.metrics_path):
            with open(self.metrics_path, 'w') as f:
                json.dump([], f)

    def evaluate_batch(
        self, 
        queries: List[str], 
        responses: List[QueryResponse], 
        meeting_id: Optional[str] = None
    ) -> EvaluationResult:
        """Evaluate a batch of RAG results using Ragas.
        """
        
        data = {
            "question": queries,
            "answer": [r["answer"] if isinstance(r, dict) else r.answer for r in responses],
            "contexts": [r["retrieved_contexts"] if isinstance(r, dict) else r.retrieved_contexts for r in responses],
            "ground_truth": [""] * len(queries) 
        }
        
        dataset = Dataset.from_dict(data)
        
        logger.info("evaluation_started", batch_size=len(queries), meeting_id=meeting_id)
        
        try:
            # We select a subset of metrics that work well without heavy ground truth settings
            # We explicitly pass the LLM and Embeddings if possible, 
            # otherwise Ragas 0.1+ uses global defaults which we set in RAGEngine
            result = evaluate(
                dataset,
                metrics=[
                    faithfulness,
                    answer_relevancy,
                    context_precision,
                ],
            )
            
            df = result.to_pandas()
            
            # Extract latency if available in responses
            latencies = [r.get("latency_ms", 0) if isinstance(r, dict) else getattr(r, "latency_ms", 0) for r in responses]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0
            
            eval_res = EvaluationResult(
                meeting_id=meeting_id,
                faithfulness=df["faithfulness"].mean(),
                answer_relevancy=df["answer_relevancy"].mean(),
                context_precision=df["context_precision"].mean(),
                context_recall=0.0,
                average_score=df[["faithfulness", "answer_relevancy", "context_precision"]].mean().mean(),
                latency_avg_ms=avg_latency
            )
            
            self._save_metrics(eval_res)
            logger.info("evaluation_completed", scores=eval_res.dict())
            return eval_res
            
        except Exception as e:
            logger.error("evaluation_failed", error=str(e))
            # Return a zeroed result if LLM evaluation fails (e.g. rate limits)
            return EvaluationResult(
                meeting_id=meeting_id,
                faithfulness=0.0,
                answer_relevancy=0.0,
                context_precision=0.0,
                context_recall=0.0,
                average_score=0.0,
                latency_avg_ms=0.0
            )

    def _save_metrics(self, result: EvaluationResult):
        """Save metrics to historical storage."""
        try:
            with open(self.metrics_path, 'r') as f:
                history = json.load(f)
            
            # Convert datetime to string for JSON serialization
            data = result.dict()
            data['timestamp'] = data['timestamp'].isoformat()
            
            history.append(data)
            
            with open(self.metrics_path, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error("metrics_save_failed", error=str(e))

    def get_historical_metrics(self) -> List[Dict[str, Any]]:
        """Retrieve all historical metrics."""
        try:
            if not os.path.exists(self.metrics_path):
                return []
            with open(self.metrics_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error("metrics_retrieval_failed", error=str(e))
            return []
