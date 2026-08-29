from __future__ import annotations

import logging
import os
import time

from dnslib import A, QTYPE, RCODE, RR
from dnslib.server import BaseResolver, DNSServer, DNSLogger

from .policy import PolicyEngine
from .store import EventStore

LOGGER = logging.getLogger(__name__)


class PolicyResolver(BaseResolver):
    def __init__(self, engine: PolicyEngine, store: EventStore):
        self.engine = engine
        self.store = store

    def resolve(self, request, handler):
        started = time.perf_counter()
        source_ip = handler.client_address[0]
        domain = str(request.q.qname)
        reply = request.reply()

        if QTYPE[request.q.qtype] != "A":
            reply.header.rcode = RCODE.NOTIMP
            return reply

        decision = self.engine.evaluate(source_ip, domain)
        if decision.action == "ALLOW" and decision.answer:
            reply.add_answer(
                RR(
                    request.q.qname,
                    QTYPE.A,
                    rdata=A(decision.answer),
                    ttl=self.engine.ttl,
                )
            )
        elif decision.action in {"BLOCK", "THROTTLE"}:
            reply.header.rcode = RCODE.REFUSED
        elif decision.action == "NXDOMAIN":
            reply.header.rcode = RCODE.NXDOMAIN
        else:
            reply.header.rcode = RCODE.SERVFAIL

        latency_ms = (time.perf_counter() - started) * 1000
        self.store.record(source_ip, decision, latency_ms)
        LOGGER.info(
            "%s %s %s %s",
            decision.agent,
            decision.domain,
            decision.action,
            decision.answer or decision.reason,
        )
        return reply


def build_runtime():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    config_path = os.getenv("POLICY_CONFIG", "/config/policies.json")
    database_path = os.getenv("DATABASE_PATH", "/data/traffic.db")
    engine = PolicyEngine(config_path)
    store = EventStore(database_path)
    return engine, store


def start_dns_server(engine: PolicyEngine, store: EventStore) -> DNSServer:
    resolver = PolicyResolver(engine, store)
    logger = DNSLogger("error", prefix=False)
    server = DNSServer(resolver, port=53, address="0.0.0.0", logger=logger)
    server.start_thread()
    return server
