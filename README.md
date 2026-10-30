# AI Office Core (Fase 1)

Sistema multi-agente local para orquestación de desarrollo de software con APIs gratuitas de LLMs.

## Características
- **Tech Lead (Gemini):** Planificación técnica modular y contextual basada en `PROJECT_MEMORY.md`.
- **Pre-Flight Syntax QA:** Compilación en memoria (`compile()`) a 0 tokens de costo.
- **DevSecOps QA:** Auditoría adversarial profunda de vulnerabilidades (OWASP CWE-22, inyecciones, criptografía).
- **Control de Filesystem:** Sanitización estricta de rutas y respaldos automáticos `.bak`.
- **Resiliencia de Red:** Backoff exponencial ante saturación HTTP 503/429.
