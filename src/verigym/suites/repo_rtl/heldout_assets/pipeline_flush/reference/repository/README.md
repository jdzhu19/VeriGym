# Flushable two-stage pipeline

This repository contains a two-stage byte pipeline. Each clock transfers the valid bit and data
through both stages; `flush` is intended to invalidate every in-flight item.
