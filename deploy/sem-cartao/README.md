# Operação sem cartão: alternativas para o Cartório Digital Bitcoin

Esta documentação **não** ativa uma carteira e não instala servidores remotamente. A implantação só acontece após o usuário disponibilizar um equipamento Linux e aprovar os controles. Para ativação financeira, ver `docs/mainnet.md`.

## Escolha realista em novembro/2026

| Opção | Cartão | Serve como nó Bitcoin Core + Core Lightning próprio? | Continuidade |
| --- | --- | --- | --- |
| Computador Linux próprio | Não | Sim, se hardware/energia/internet suficientes | Depende de seu equipamento, energia e provedor de internet |
| Openworld VPS gratuita | Não (cadastro por Discord) | **Não aprovada para BTC real**; para laboratório temporário somente | Requer renovação a cada 7 dias; recursos/segurança/volume não garantidos |
| GitHub Codespaces | Cota gratuita na conta pessoal | Não é servidor financeiro permanente | Suspensão e limites de computação/armazenamento |
| Blink Wallet/API | Não pede cartão para cadastro por telefone | **Não** é nó próprio nem ganha taxas de roteamento | Recebimentos Lightning via provedor custodial, sujeitos a termos, limites e riscos |
| Vercel + Supabase | Dependem do plano e do recurso | Não substituem o nó | Úteis para site, cadastros e metadados |

Fontes:
- GitHub Codespaces: https://docs.github.com/pt/codespaces/troubleshooting/troubleshooting-included-usage
- Openworld: https://openworld.eu.org/faq
- Core Lightning/Tor: https://docs.corelightning.org/docs/tor
- Core Lightning/Bitcoin Core podado: https://docs.corelightning.org/docs/bitcoin-core
- Blink Wallet/API: https://faq.blink.sv/creating-a-blink-account/what-information-do-i-need-to-provide-to-register-to-blink e https://dev.blink.sv/api/auth

## Perfil A: nó próprio em casa, sem mensalidade de hospedagem

Use computador já disponível, preferencialmente dedicado, com **4 GB de RAM (8+ preferível)**, **SSD de 256 GB ou mais**, internet de banda larga estável e fonte de energia confiável. O software pode ser gratuito, mas energia, conexão, SSD e backups possuem custos reais.

1. Instale Debian/Ubuntu suportado, ative atualizações de segurança, firewall e SSH com chaves, proteja o acesso físico e configure religamento após queda de energia. Nunca execute os nós usando os diretórios regtest existentes.
2. Instale Bitcoin Core e Core Lightning **verificando as assinaturas dos binários oficiais** e compatibilidade com o sistema. Faça sincronização inicial completa da cadeia (mesmo com pruning o Core baixa/verifica histórico). Em conexão limitada, isso pode consumir centenas de GB de tráfego uma vez.
3. Use `bitcoin.conf.example` abaixo como ponto de partida; o nó valida mainnet mas mantém somente blocos recentes. Confira caminho, ponto de montagem e permissões; nunca exponha RPC 8332, nem use carteira do Core para financiar o CLN sem procedimento próprio. Um Bitcoin Core podado não preserva histórico para outros serviços.
4. Para permitir conexões Lightning recebidas sem IP público fixo, instale **Tor no mesmo computador** e configure um serviço onion v3 usando `torrc.lightning.example`. Substitua `announce-addr` no exemplo Lightning pelo onion gerado pelo Tor. Se preferir que o CLN crie o onion com `statictor`, siga o manual oficial e libere apenas o cookie de controle Tor com permissões mínimas; não copie segredos para o GitHub.
5. Mantenha o Bitcoin Core sincronizado e CLN online. **Atenção:** se o CLN ficar muitos blocos atrás e o Core eliminar blocos de que ele ainda precisa, não conseguirá mais sincronizar sem intervenção; configure alertas e monitore continuamente a diferença de alturas.
6. Antes de criar faturas, siga `docs/mainnet.md`: identidade permanente, arquivos privados, Rune CLNRest restrita, backups **externos** separados da carteira/canais, teste de restauração, worker systemd e `doctor`. O backup do cartório não recupera fundos/canais Lightning. Instalar um nó NÃO cria liquidez de entrada.
7. Com Core/CLN em PATH e o diretório de dados já criado, executar o pré-diagnóstico (ajuste capacidade aos discos efetivos):
   ```bash
   python3 deploy/mainnet/host_preflight.py --data-dir /var/lib/bitcoind --min-volume-gib 180 --min-ram-gib 4 --min-free-gib 40
   ```
   Resultado positivo **não** autoriza BTC real: apenas verifica recursos superficiais do host. `doctor`, restore, monitoramento e capacidade de recebimento são pré-requisitos adicionais.
8. Manter `allow_mainnet_invoices=false` durante instalação, toda sincronização e testes. Para pagamentos reais, exigir limites financeiros e autorização explícita do operador. Não habilitar movimentações automaticamente.

Se **não houver computador próprio**, não há nesta análise provedora gratuita, sem cartão, verificada para hospedagem **financeira** 24h e armazenamento/segurança suficientes. Não coloque seeds/fundos em VPS gratuita comunitária.

## Perfil B: cobrar pelo registro sem hospedar nó próprio

A Blink fornece carteira Lightning e API de recebimento sem cartão no cadastro por telefone. **Ela não opera um nó Bitcoin Core sob seu controle e não gera taxas de roteamento próprias.** O modelo de conta padrão é custodial e pode impor taxas, limites e disponibilidade.

- Criar conta do titular pelo site/aplicativo oficial; conferir suporte regional, termos e política de custódia.
- Criar chave de API apenas com permissões **Read + Receive** (não Write). Guardar em gerenciador de segredos do backend; **nunca** em front-end ou repositório. Não digitar segredo no chat.
- Antes de implementar o adaptador de faturamento, definir formato das faturas, mecanismo server-side de confirmação, política de expiração/reembolso, duplicidade/idempotência, conciliação, taxas e fluxo de custódia.
- **Esta branch não integra a API Blink nem aceita pagamentos Blink**: o módulo atual valida recebimentos via Core Lightning. Não marcar registro como pago sem confirmação independente autenticada da fonte de pagamento.
- Testar recebimentos pequenos com fundos autorizados antes de operar um serviço comercial. Não manter saldo significativo em custódia.

## O que foi preparado no GitHub

- Exemplos de Bitcoin Core podado, Tor e Lightning.
- Roteiro explícito de instalação sem cartão e critérios de **não ativar** fundos.
- `docs/mainnet.md` e `docs/go-live-mainnet.md` permanecem as referências de recuperação, diagnóstico e ativação.

**Nenhuma instalação remota, carteira criada, fatura emitida, BTC recebido ou nó sincronizado foi realizada por esta alteração.**
