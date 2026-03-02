"""Four tools for the eMMC LangGraph agent.

Each tool is defined as a closure over (retriever, store, embedder, llm) so
there are no global variables.  Call build_tools() to instantiate all four.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool

if TYPE_CHECKING:
    from ..retrieval.embedder import BGEEmbedder
    from ..retrieval.vectorstore import EMMCVectorStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TRAN_SPEED decode tables (CSD [103:96])
# ---------------------------------------------------------------------------

_FREQ_UNIT = {0: 100e3, 1: 1e6, 2: 10e6, 3: 100e6}  # Hz
_MULT = {
    1: 1.0, 2: 1.2, 3: 1.3, 4: 1.5, 5: 2.0, 6: 2.5, 7: 3.0, 8: 3.5,
    9: 4.0, 10: 4.5, 11: 5.0, 12: 5.5, 13: 6.0, 14: 7.0, 15: 8.0,
}


# ---------------------------------------------------------------------------
# build_tools()
# ---------------------------------------------------------------------------

def build_tools(retriever, store: "EMMCVectorStore", embedder: "BGEEmbedder", llm) -> list[BaseTool]:
    """Initialise all four agent tools and return them as a list.

    Tools capture (retriever, store, embedder, llm) via closure — no globals.

    Args:
        retriever: HybridRetriever or EMMCRetriever instance.
        store:     EMMCVectorStore (for glossary lookups).
        embedder:  BGEEmbedder (for explain_term vector search).
        llm:       ChatOpenAI-compatible LLM (for internal query expansion).

    Returns:
        [search_emmc_docs, explain_term, compare_versions, calculate]
    """
    from ..qa.chain import _expand_queries, format_docs_with_citations

    # ------------------------------------------------------------------
    # Tool 1: search_emmc_docs
    # ------------------------------------------------------------------

    @tool
    def search_emmc_docs(query: str, version: str = "") -> str:
        """Search the eMMC (JEDEC JESD84) specification for technical content.

        Use this for register definitions, command descriptions, timing parameters,
        protocol flows, or any fact from the eMMC specification.

        Args:
            query: The technical query in English, using spec terminology.
                   Include register names (e.g. EXT_CSD, BKOPS_EN), hex values,
                   command names (CMD6, CMD46), and timing mode names (HS200, HS400).
            version: Optional version filter. One of "5.1", "5.0", "4.51", or ""
                     (empty = use session default, usually "5.1").

        Returns:
            Formatted excerpts with Cite-as tags for inline citation.
        """
        from langchain_core.documents import Document

        # Override retriever default version if caller supplied one
        original_version = getattr(retriever, "default_version", "")
        if version:
            try:
                retriever.default_version = version  # type: ignore[attr-defined]
            except Exception:
                pass

        try:
            variants = _expand_queries(query, llm)
            logger.info("search_emmc_docs variants: %s", variants)

            seen: dict[str, Document] = {}
            for q in [query] + variants:
                for doc in retriever.invoke(q):
                    cid = doc.metadata.get("_id") or doc.page_content[:64]
                    if cid not in seen:
                        seen[cid] = doc

            docs = list(seen.values())[:15]
            if not docs:
                return "No relevant content found in the eMMC specification for this query."
            return format_docs_with_citations(docs)
        finally:
            if version:
                try:
                    retriever.default_version = original_version  # type: ignore[attr-defined]
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Tool 2: explain_term
    # ------------------------------------------------------------------

    @tool
    def explain_term(term: str) -> str:
        """Look up the definition of an eMMC technical term or abbreviation.

        Use this when the user asks what an abbreviation means (e.g. BKOPS, FFU,
        CMDQ, HPI, RPMB) or requests a concise definition before deeper analysis.

        Args:
            term: The term or abbreviation to look up (e.g. "BKOPS", "FFU", "HS400").

        Returns:
            Definition(s) found in the eMMC glossary, or a message if not found.
        """
        vec = embedder.embed_query(term)
        hits = store.query(vec, n_results=5, collection="glossary")
        if not hits:
            return f'No definition found for "{term}" in the eMMC glossary. Try search_emmc_docs for more context.'

        parts = []
        for i, hit in enumerate(hits, 1):
            m = hit["metadata"]
            source = m.get("source", "unknown")
            page = m.get("page_start", "?")
            parts.append(f"[{i}] {source} p.{page}\n{hit['document']}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Tool 3: compare_versions
    # ------------------------------------------------------------------

    @tool
    def compare_versions(feature: str, versions: str = "4.51,5.0,5.1") -> str:
        """Compare an eMMC feature or register field across multiple spec versions.

        Use this when the user asks about differences between eMMC versions,
        or when version-specific behavior needs to be highlighted.

        Args:
            feature: The feature, register, or command to compare
                     (e.g. "HS400 timing", "CACHE_CTRL", "Command Queuing support").
            versions: Comma-separated spec versions to compare.
                      Defaults to "4.51,5.0,5.1" (all three versions).

        Returns:
            Version-grouped excerpts formatted as a comparison table.
        """
        from langchain_core.documents import Document

        ver_list = [v.strip() for v in versions.split(",") if v.strip()]
        original_version = getattr(retriever, "default_version", "")

        sections: list[str] = []
        for ver in ver_list:
            try:
                retriever.default_version = ver  # type: ignore[attr-defined]
            except Exception:
                pass

            try:
                docs: list[Document] = retriever.invoke(feature)
            except Exception as exc:
                logger.warning("compare_versions retrieval failed for %s: %s", ver, exc)
                docs = []
            finally:
                try:
                    retriever.default_version = original_version  # type: ignore[attr-defined]
                except Exception:
                    pass

            ver_docs = [d for d in docs if d.metadata.get("version") == ver]

            ver_label_map = {"4.51": "eMMC 4.51 (JESD84-B451)", "5.0": "eMMC 5.0 (JESD84-B50)", "5.1": "eMMC 5.1 (JESD84-B51)"}
            label = ver_label_map.get(ver, f"eMMC {ver}")

            if ver_docs:
                sections.append(f"## {label}\n{format_docs_with_citations(ver_docs)}")
            else:
                sections.append(f"## {label}\n该版本未检索到与「{feature}」相关的内容。")

        return "\n\n".join(sections) if sections else "No relevant content found for version comparison."

    # ------------------------------------------------------------------
    # Tool 4: calculate
    # ------------------------------------------------------------------

    @tool
    def calculate(formula: str, parameters: dict) -> str:
        """Perform eMMC specification calculations using official formulas.

        Supported formulas and their required parameter keys:
        - boot_size       : {"boot_size_mult": int}
        - rpmb_size       : {"rpmb_size_mult": int}
        - capacity        : {"sec_count": int}
        - tran_speed      : {"freq_unit": int, "mult": int}
        - erase_group     : {"hc_erase_grp_size": int}
        - wp_group        : {"hc_wp_grp_size": int, "hc_erase_grp_size": int}
        - sleep_current   : {"s_c_vcc": int}
        - gp_size         : {"gp_size_mult": int, "hc_erase_grp_size": int, "hc_wp_grp_size": int}

        Args:
            formula: Formula name (one of the supported names above).
            parameters: Dict of integer register values required by the formula.

        Example:
            calculate(formula="boot_size", parameters={"boot_size_mult": 16})
            → "Boot partition size = 128 KB × 16 = 2048 KB = 2 MB  [EXT_CSD[226]]"

        Returns:
            Step-by-step calculation result with spec reference.
        """
        formula = formula.strip().lower()
        try:
            return _dispatch_formula(formula, parameters)
        except (KeyError, TypeError, ValueError) as exc:
            return f"Calculation error for formula '{formula}': {exc}. Check parameter names and types."

    return [search_emmc_docs, explain_term, compare_versions, calculate]


# ---------------------------------------------------------------------------
# Formula implementations
# ---------------------------------------------------------------------------

def _dispatch_formula(formula: str, kwargs: dict) -> str:
    if formula == "boot_size":
        m = int(kwargs["boot_size_mult"])
        kb = 128 * m
        mb = kb / 1024
        return (
            f"Boot partition size = 128 KB × {m} = {kb} KB"
            + (f" = {mb:.0f} MB" if kb >= 1024 else "")
            + "  [EXT_CSD[226] BOOT_SIZE_MULT]"
        )

    if formula == "rpmb_size":
        m = int(kwargs["rpmb_size_mult"])
        kb = 128 * m
        mb = kb / 1024
        return (
            f"RPMB partition size (per partition) = 128 KB × {m} = {kb} KB"
            + (f" = {mb:.0f} MB" if kb >= 1024 else "")
            + "  [EXT_CSD[168] RPMB_SIZE_MULT]"
        )

    if formula == "capacity":
        sec = int(kwargs["sec_count"])
        total_bytes = sec * 512
        gib = total_bytes / (1024 ** 3)
        gb = total_bytes / (10 ** 9)
        return (
            f"Device capacity = SEC_COUNT × 512 bytes = {sec} × 512 = {total_bytes:,} bytes"
            f" ≈ {gib:.2f} GiB ({gb:.2f} GB)  [EXT_CSD[215:212] SEC_COUNT]"
        )

    if formula == "tran_speed":
        fu = int(kwargs["freq_unit"])
        mult = int(kwargs["mult"])
        if fu not in _FREQ_UNIT:
            return f"Invalid freq_unit={fu}. Valid values: {list(_FREQ_UNIT.keys())}."
        if mult not in _MULT:
            return f"Invalid mult={mult}. Valid values: {list(_MULT.keys())}."
        hz = _FREQ_UNIT[fu] * _MULT[mult]
        mhz = hz / 1e6
        return (
            f"TRAN_SPEED decode: freq_unit={fu} → {_FREQ_UNIT[fu]/1e6:.1f} MHz base"
            f", mult={mult} → ×{_MULT[mult]}"
            f"\nResult = {_FREQ_UNIT[fu]/1e6:.1f} × {_MULT[mult]} = {mhz:.1f} MHz"
            "  [CSD[103:96] TRAN_SPEED]"
        )

    if formula == "erase_group":
        hc = int(kwargs["hc_erase_grp_size"])
        kb = (hc + 1) * 512
        mib = kb / 1024
        return (
            f"Erase group size = (HC_ERASE_GRP_SIZE + 1) × 512 KB"
            f" = ({hc} + 1) × 512 = {kb} KB"
            + (f" = {mib:.0f} MiB" if kb >= 1024 else "")
            + "  [EXT_CSD[224] HC_ERASE_GRP_SIZE]"
        )

    if formula == "wp_group":
        hc_wp = int(kwargs["hc_wp_grp_size"])
        hc_erase = int(kwargs["hc_erase_grp_size"])
        erase_kb = (hc_erase + 1) * 512
        wp_kb = (hc_wp + 1) * erase_kb
        mib = wp_kb / 1024
        return (
            f"Write protect group size = (HC_WP_GRP_SIZE + 1) × erase_group_size"
            f" = ({hc_wp} + 1) × {erase_kb} KB = {wp_kb} KB"
            + (f" = {mib:.0f} MiB" if wp_kb >= 1024 else "")
            + "  [EXT_CSD[221] HC_WP_GRP_SIZE]"
        )

    if formula == "sleep_current":
        s = int(kwargs["s_c_vcc"])
        ua = 2 ** s
        return (
            f"Sleep mode max current = 1 µA × 2^(S_C_VCC) = 1 × 2^{s} = {ua} µA"
            "  [EXT_CSD[143] S_C_VCC]"
        )

    if formula == "gp_size":
        gp_mult = int(kwargs["gp_size_mult"])
        hc_erase = int(kwargs["hc_erase_grp_size"])
        hc_wp = int(kwargs["hc_wp_grp_size"])
        erase_kb = (hc_erase + 1) * 512
        wp_kb = (hc_wp + 1) * erase_kb
        gp_kb = gp_mult * wp_kb
        mib = gp_kb / 1024
        return (
            f"GP partition size = GP_SIZE_MULT × wp_group_size"
            f" = {gp_mult} × {wp_kb} KB = {gp_kb} KB"
            + (f" = {mib:.0f} MiB" if gp_kb >= 1024 else "")
            + "  [EXT_CSD[154:143] GP_SIZE_MULT]"
        )

    supported = ["boot_size", "rpmb_size", "capacity", "tran_speed",
                 "erase_group", "wp_group", "sleep_current", "gp_size"]
    return f"Unknown formula '{formula}'. Supported: {supported}."
