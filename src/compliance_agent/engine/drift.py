"""Drift detection engine — bridge to LegalDrift for semantic drift detection."""

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


class DriftBridge:
    """Wraps LegalDrift for policy version comparison.

    Requires: pip install legaldrift
    """

    def __init__(self):
        self._legaldrift = None

    def _ensure_legaldrift(self):
        if self._legaldrift is not None:
            return
        try:
            from legaldrift import DriftDetector, EmbeddingEngine, LegalDocument

            self._legaldrift = {
                "DriftDetector": DriftDetector,
                "EmbeddingEngine": EmbeddingEngine,
                "LegalDocument": LegalDocument,
            }
        except ImportError:
            raise RuntimeError(
                "LegalDrift is not installed. Install it with: pip install legaldrift"
            )

    def detect(
        self,
        baseline_path: str,
        current_path: str,
        chunked: bool = False,
        output_format: str = "table",
    ) -> dict:
        """Detect semantic drift between two policy documents.

        Args:
            baseline_path: Path to the original policy version.
            current_path: Path to the updated policy version.
            chunked: If True, do section-by-section comparison.
            output_format: 'table' or 'json'.

        Returns:
            Dict with drift detection results.
        """
        self._ensure_legaldrift()

        baseline_text = Path(baseline_path).read_text(encoding="utf-8")
        current_text = Path(current_path).read_text(encoding="utf-8")

        engine = self._legaldrift["EmbeddingEngine"]()
        detector = self._legaldrift["DriftDetector"](threshold=0.05)

        if chunked:
            return self._detect_chunked(baseline_text, current_text, engine, detector, output_format)
        else:
            return self._detect_full(baseline_text, current_text, engine, detector, output_format)

    def _detect_full(
        self,
        baseline_text: str,
        current_text: str,
        engine,
        detector,
        output_format: str,
    ) -> dict:
        emb1 = engine.encode([baseline_text])
        emb2 = engine.encode([current_text])
        result = detector.detect(emb1, emb2)

        output = {
            "drift_detected": result.drift_detected,
            "p_value": result.p_value,
            "confidence": 1.0 - result.p_value,
            "severity": result.severity,
            "effect_size": getattr(result, "effect_size", None),
            "test_results": getattr(result, "test_results", {}),
        }

        if output_format == "table":
            self._print_table(output)
        elif output_format == "json":
            console.print(json.dumps(output, indent=2, default=str))

        return output

    def _detect_chunked(
        self,
        baseline_text: str,
        current_text: str,
        engine,
        detector,
        output_format: str,
    ) -> dict:
        from legaldrift import align_chunks, chunk_by_sections

        doc1 = self._legaldrift["LegalDocument"](text=baseline_text, document_id="baseline")
        doc2 = self._legaldrift["LegalDocument"](text=current_text, document_id="current")

        chunks1 = chunk_by_sections(doc1)
        chunks2 = chunk_by_sections(doc2)

        section_results = []
        for c1, c2 in align_chunks(chunks1, chunks2):
            if c1 is None:
                section_results.append(
                    {"section": c2.metadata.get("header", "Unknown"), "status": "ADDED"}
                )
                continue
            if c2 is None:
                section_results.append(
                    {"section": c1.metadata.get("header", "Unknown"), "status": "REMOVED"}
                )
                continue

            e1 = engine.encode([c1.text])
            e2 = engine.encode([c2.text])
            r = detector.detect(e1, e2)

            section_results.append(
                {
                    "section": c1.metadata.get("header", f"Section {c1.chunk_index}"),
                    "status": "DRIFT" if r.drift_detected else "OK",
                    "p_value": r.p_value,
                    "severity": r.severity,
                }
            )

        output = {"chunked": True, "sections": section_results}

        if output_format == "table":
            self._print_chunked_table(section_results)
        elif output_format == "json":
            console.print(json.dumps(output, indent=2, default=str))

        return output

    def _print_table(self, result: dict) -> None:
        """Print full-document drift results as a table."""
        drift = result["drift_detected"]
        status = "[red]DRIFT DETECTED[/red]" if drift else "[green]NO DRIFT[/green]"

        table = Table(title="Drift Detection Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Status", status)
        table.add_row("P-value", f"{result['p_value']:.4f}")
        table.add_row("Confidence", f"{result['confidence']:.2%}")
        table.add_row("Severity", f"{result['severity']:.4f}")

        if result.get("effect_size") is not None:
            table.add_row("Effect Size", f"{result['effect_size']:.4f}")

        for test_name, test_data in result.get("test_results", {}).items():
            if isinstance(test_data, dict):
                table.add_row(f"  {test_name}", f"p={test_data.get('p_value', 'N/A'):.4f}")

        console.print(table)

    def _print_chunked_table(self, sections: list[dict]) -> None:
        """Print chunked drift results as a table."""
        table = Table(title="Section-by-Section Drift Detection")
        table.add_column("Status", style="bold", width=10)
        table.add_column("Section", style="cyan")
        table.add_column("P-value", width=10)
        table.add_column("Severity", width=10)

        for s in sections:
            status_icon = {
                "DRIFT": "[red]DRIFT[/red]",
                "OK": "[green]OK[/green]",
                "ADDED": "[yellow]NEW[/yellow]",
                "REMOVED": "[dim]GONE[/dim]",
            }.get(s["status"], s["status"])

            p_val = f"{s.get('p_value', 'N/A'):.4f}" if isinstance(s.get("p_value"), float) else "N/A"
            severity = f"{s.get('severity', 'N/A'):.4f}" if isinstance(s.get("severity"), float) else "N/A"

            table.add_row(status_icon, s["section"], p_val, severity)

        console.print(table)
