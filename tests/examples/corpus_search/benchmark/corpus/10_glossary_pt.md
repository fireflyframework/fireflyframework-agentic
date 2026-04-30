# Acme Corp — Glossário Técnico (Português)

Última atualização: 2026-02-20.

Este glossário define os termos técnicos utilizados pela equipe Acme em
documentação interna e externa. As definições são aplicáveis em todos os
mercados onde a Acme opera, com adaptações específicas para o Brasil.

## Termos gerais

**API Bolt v2/v3** — Interface de programação da Acme Corp para fluxos de
trabalho de documentos transacionais. A versão v3 está prevista para
disponibilidade geral no terceiro trimestre de 2026.

**Assinatura eletrónica qualificada** — Assinatura digital que cumpre os
requisitos do Regulamento eIDAS (UE 910/2014). Na Acme, é fornecida em
parceria com a Trustico-PT.

**Assinatura ICP-Brasil** — Assinatura digital baseada na Infraestrutura de
Chaves Públicas Brasileira, equivalente brasileira da assinatura qualificada
europeia. Suportada pela Acme via parceria com certificadoras AC-RAIZ.

**Auditoria** — Conjunto imutável de eventos registados para cada documento
assinado, retidos por **10 anos** conforme requisito eIDAS e ICP-Brasil.

**Cliente** — Tenant que possui uma conta paga na Acme. Cada cliente recebe
um identificador único (`tenant_id`) e dados isolados em nível de banco de
dados.

**Documento** — Ficheiro PDF, DOCX, JPG ou PNG enviado ao Acme Bolt para
assinatura. Limite máximo: 50 MB por documento.

**eIDAS** — Regulamento europeu 910/2014 sobre identificação eletrónica e
serviços de confiança. Define três níveis de assinatura: simples, avançada
e qualificada.

**Failover** — Processo automático de transferência de tráfego entre
regiões em caso de indisponibilidade. Acme suporta failover automático
entre eu-west-1 e eu-west-2 com RTO de 90 segundos.

**HMAC-SHA256** — Algoritmo utilizado para assinar webhooks da Acme,
permitindo que o destinatário verifique a autenticidade da entrega.

**LGPD** — Lei Geral de Proteção de Dados (Lei 13.709/2018), legislação
brasileira de proteção de dados pessoais, equivalente brasileira do RGPD
europeu. Acme cumpre integralmente a LGPD para clientes brasileiros.

**MFA (Autenticação Multi-Factor)** — Obrigatório em todas as contas
administrativas da Acme. Métodos suportados: TOTP, chaves WebAuthn (FIDO2),
e push para o app Acme Authenticator.

**NRR (Net Revenue Retention)** — Métrica de retenção de receita líquida.
A Acme reportou NRR de 118% no quarto trimestre de 2025.

**RGPD / GDPR** — Regulamento Geral de Proteção de Dados europeu (UE
2016/679). Aplicável a todos os clientes que processam dados de cidadãos
da União Europeia.

**RPO (Recovery Point Objective)** — Objetivo de ponto de recuperação. Para
o Acme Bolt, o RPO é de zero (replicação síncrona multi-AZ).

**RTO (Recovery Time Objective)** — Objetivo de tempo de recuperação. Para
falhas regionais, RTO de 90 segundos via replicação cross-region.

**SLA** — Service Level Agreement. O Acme Bolt garante 99,95% de
disponibilidade mensal.

**SOC 2** — Padrão de auditoria desenvolvido pelo American Institute of
Certified Public Accountants. A Acme possui atestação SOC 2 Tipo II
desde 2021.

**Tenant** — Sinónimo de **cliente**. Unidade de isolamento lógico no
sistema multi-tenant da Acme.

**Webhook** — Notificação HTTP enviada pela Acme para um URL configurado
pelo cliente quando ocorre um evento (assinatura completada, documento
rejeitado, etc.). Entregas seguem garantia at-least-once com assinatura
HMAC-SHA256.
