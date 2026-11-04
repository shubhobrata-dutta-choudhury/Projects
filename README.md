# Shubhobrata Dutta Choudhury

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue?style=flat&logo=linkedin)](https://www.linkedin.com/in/shubhobrata-dutta-choudhury)
[![Email](https://img.shields.io/badge/Email-shubhobrata2008%40gmail.com-red?style=flat&logo=gmail)](mailto:shubhobrata2008@gmail.com)

**Senior Applied AI Engineer, Lead Systems Architect & Ph.D. Scholar**  
Specializing in Production AI Systems, Enterprise RAG Platforms, Agentic Workflows, and Scalable ML Infrastructure.

---

## 👨‍💻 Professional Summary

I am a **Senior Applied AI Engineer and Systems Architect with 7+ years of software engineering experience**, specializing in production AI systems, enterprise RAG platforms, and multi-stage ML workflows. Currently working as a **Lead Engineer at Qualcomm**, I design high-throughput AI services and hybrid search platforms serving global engineering teams, sustaining peak loads of 50–100 RPS at sub-120ms p95 latency with 99.9% uptime.

Parallel to my industry execution, I am pursuing my **Ph.D. in Computer Science at BITS Hyderabad**, focusing on **Reliable AI, Uncertainty Quantification (UQ), Out-of-Distribution (OOD) Detection, and Statistical Drift Monitoring**.

* **Patents & IP**: Primary and co-inventor on **14+ patent filings** (5 US Grants, 8 Worldwide Grants) covering algorithmic data processing, computational optimization, execution runtimes, and automated defect detection.
* **Honors**: Recipient of **two Qualcomm Orion Awards** for technical execution, engineering leadership, and high-impact software delivery.

---

## 🛠️ Core Competencies & Technical Stack

```text
+-----------------------------------------------------------------------------------+
|  Applied AI & Agents   :: Multi-step Orchestration, FSM Pipelines, Hybrid RAG     |
|                           (BM25 + Dense Search: Milvus/Faiss), RRF, Cross-Encoder |
|  Production Infra      :: Python, FastAPI, gRPC, Docker, Kubernetes (GKE), Redis |
|  ML & MLOps            :: PyTorch, TensorFlow, JAX, MLflow, Airflow, PySpark,     |
|                           Statistical Drift Monitoring (PSI / KS Tests)           |
|  Reliable AI Research  :: Uncertainty Quantification (UQ), OOD Detection         |
+-----------------------------------------------------------------------------------+
```

- **Applied AI & Agentic Systems**: Multi-agent Orchestration, Finite State Machine (FSM) Execution, Enterprise RAG, Hybrid Retrieval, Reciprocal Rank Fusion (RRF), Cross-Encoder Re-ranking, LLM-as-a-Judge Evaluation.
- **Production AI Infrastructure**: Python, FastAPI, gRPC microservices, Docker, Kubernetes (GKE), Redis, PostgreSQL, Distributed Multi-GPU Inference, High-Throughput Microservices.
- **ML Engineering & MLOps**: PyTorch, TensorFlow, Scikit-learn, MLflow, Apache Airflow, PySpark, Automated CI/CD Regression Benchmarking, Statistical Drift Monitoring (PSI/KS Tests), Synthetic Data Generation (Diffusion/GANs).

---

## 🚀 Featured Projects & Repositories

> ⚠️ **Note on Repository Status**: This GitHub profile serves as a central hub for my open-source systems, research prototypes, and software architecture designs. **Several projects are actively under development**, undergoing refactoring, benchmarking, or migration from internal research environments.

### 📍 [AutonomousSpec2Code](./AutonomousSpec2Code) *(Active Development)*
*An Enterprise-Grade, Agentic Code Generation, Self-Correction & Evaluation Pipeline.*
* **Deterministic FSM Engine**: Orchestrates execution across strict state boundaries (`INGEST_SPEC` → `GENERATE_CODE` → `STATIC_AST_CHECK` → `EXECUTE_SANDBOX_TESTS` → `DIAGNOSE_AND_REPAIR` → `EVALUATE_QUALITY` → `COMPLETED`/`FAILED`).
* **Static AST Guardrail & Security Policy**: Enforces security constraints before execution by flagging forbidden imports (`os`, `subprocess`, `sys`) and unsafe callables (`eval`, `exec`). Computes public function type-hint and docstring coverage telemetry.
* **Isolated Subprocess Sandboxing**: Executes target code and acceptance test suites inside isolated `pytest` subprocess environments with hard timeout protection.
* **Surgical Self-Correction & Repair**: Automatically routes traceback failures and AST violations to a specialized Repair Agent, applying structured search-and-replace patches (`SearchReplacePatch`) within configured retry budgets ($Pass@k$).
* **Dual-Layer Benchmarking**: Combines objective execution metrics ($Pass@1$, $Pass@k$, recovery rate) with a 4-dimension LLM-as-a-Judge qualitative rubric.

---

### 🚧 Ongoing & Upcoming Open-Source Work

* **Enterprise Hybrid RAG Engine**: Microservice implementation combining BM25 lexical search, dense vector retrieval (Faiss/Milvus), and RRF re-ranking for ultra-low latency technical search.
* **Reliable AI & Drift Monitoring Suite**: Python toolkit for statistical drift detection using Population Stability Index (PSI) and Kolmogorov-Smirnov (KS) tests, alongside uncertainty calibration metrics.
* **Generative Edge Data Synthesizer**: Conditional diffusion and GAN pipeline utilities for generating validated edge scenarios for model stress testing.

---

## 🎓 Education & Academic Background

* **Ph.D. in Computer Science** *(Ongoing)*  
  *Birla Institute of Technology and Science (BITS), Hyderabad*  
  **Research Area**: Reliable AI, Uncertainty Quantification & Statistical Drift Monitoring

* **M.Tech. in Electrical Engineering** *(2021 – 2023)*  
  *Indian Institute of Technology (IIT), Madras* | **CGPA: 9.64 / 10.0**

* **B.Tech. in Engineering Physics** *(2014 – 2018)*  
  *Delhi Technological University (DTU), Delhi* | **CGPA: 8.6 / 10.0**

---

## 🏆 Key Industry Accomplishments (Qualcomm)

* **Enterprise Generative AI Search Platform**: Architected a multi-site AI search engine indexing 25,000+ technical assets across India, US, and China, improving NDCG@10 by 24% and saving 1,500+ engineering hours annually.
* **High-Throughput Microservices**: Built multi-GPU FastAPI & gRPC inference microservices sustaining peak loads of 50–100 RPS at sub-120ms p95 latency with 99.9% uptime.
* **Synthetic Data Generation**: Engineered conditional diffusion and GAN pipelines generating 50,000+ edge-case scenarios, boosting model robustness by 42% on long-tail distributions.

---

## 📫 Connect & Collaborate

* **Email**: [shubhobrata2008@gmail.com](mailto:shubhobrata2008@gmail.com)
* **LinkedIn**: [linkedin.com/in/shubhobrata-dutta-choudhury](https://www.linkedin.com/in/shubhobrata-dutta-choudhury)
* **GitHub**: [github.com/shubhobrata-dutta-choudhury](https://github.com/shubhobrata-dutta-choudhury)
