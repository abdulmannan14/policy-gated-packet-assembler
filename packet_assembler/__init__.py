"""Minimal Policy-Gated Packet Assembler.

A small command-line tool that ingests a YAML component definition,
assembles a "micro-packet", runs it through an explicit policy gate,
and either emits a signed (hashed) packet or a structured rejection.
"""

__version__ = "0.1.0"
