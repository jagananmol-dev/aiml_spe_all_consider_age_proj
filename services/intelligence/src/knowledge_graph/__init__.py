# Python package init files
"""
VEDA AI — Knowledge Graph Module

Continuous knowledge graph maintenance system that keeps the
organizational "brain" alive by processing every document through
entity extraction → graph upsert → relationship building.

Components:
- graph_manager: Apache AGE operations (upsert nodes, create edges, consolidate)
- graph_worker: Kafka consumer for continuous graph maintenance
- ChunkBuilder: graph-enriched LLM context (nlp_sts/step10_context_building.py)
"""

from nlp_sts.step10_context_building import ChunkBuilder

from .graph_manager import KnowledgeGraphManager

__all__ = ["ChunkBuilder", "KnowledgeGraphManager"]
