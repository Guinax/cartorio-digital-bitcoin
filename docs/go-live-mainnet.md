# Go-live controlado: Cartório Digital Bitcoin (mainnet)

**Estado:** roteiro de preparação. **Não significa que o servidor esteja contratado, instalado ou recebendo BTC.** Nunca habilitar `allow_mainnet_invoices` somente porque CI/regtest passaram.

## Hospedagem recomendada (01/11/2026)

- **Preferência: Hetzner Dedicated AX42 com upgrade para 2 × 2 TB NVMe** (validar preço final e disponibilidade na configuração), Debian 13 ou Ubuntu 24.04 LTS, RAID1 e endereço IP dedicado. A série AX42 tem 64 GB RAM, CPU Ryzen 7, uplink 1 Gbps e suporte a upgrades de disco. Os 2 × 512 GB **padrão não servem** para um nó arquival crescente com redundância.
- Alternativa com discos inclusos: **Hetzner EX63-2, 2 × 1,92 TB NVMe** (mais caro; confirmar valor final e impostos).
- Alternativa comercial: **OVHcloud So you Start/Rise**, procurando 2 × pelo menos 1,92 TB SSD/NVMe, tráfego compatível e RAID1.
- Exigir capacidade **utilizável** >= 1,5 TiB (após RAID1, SO e reservas), pelo menos 8 GiB RAM (preferir 16+), conexão estável 24/7, suporte de recuperação, backups externos e acesso administrativo com MFA.
- Atenção: RAID1 só protege de falha isolada do disco. Não substitui backup e não torna o host altamente disponível.
- Referências de fornecedores: https://www.hetzner.com/dedicated-rootserver/ax42/ , https://www.hetzner.com/dedicated-rootserver/ex63/ e https://eco.ovhcloud.com/pt/compare/
- Preço e contratação são responsabilidade do operador. **Não há compra efetuada**.

## Preparação e fases de aprovação

1. **Contrato e acesso.** Criar a conta do provedor diretamente (MFA, faturamento sob controle do operador), contratar o servidor, instalar Debian/Ubuntu, configurar SSH apenas por chaves, firewall, atualização de segurança, horário NTP, monitoramento e alertas fora do servidor. Manter RPC Bitcoin, socket Lightning, CLNRest, portas de banco e arquivos privados inacessíveis pela internet. Não cadastrar senhas, chaves privadas, mnemônicos ou Runes no GitHub.
2. **Disco e software.** Montar armazenamento persistente confiável e verificar status de RAID e alertas SMART. Instalar binários oficiais Bitcoin Core e Core Lightning por procedimento de distribuição verificável. Conferir checksums e **assinaturas** dos binários. Não usar releases copiadas de chats ou URLs não verificadas. Exemplo: https://bitcoincore.org/en/download/ .
3. **Pré-verificação não financeira.** Depois que `/var/lib/bitcoind` existir e as ferramentas estiverem no PATH, executar:
   ```bash
   python3 deploy/mainnet/host_preflight.py --data-dir /var/lib/bitcoind
   ```
   Deve retornar JSON com todos os `ok=true` e código de saída 0. Este programa **não testa configuração, rede ou canal** e não habilita cobranças. A capacidade deve ser conferida também com `lsblk`, RAID e ponto de montagem reais.
4. **Core na rede certa.** Configurar `deploy/mainnet/bitcoin.conf.example` em instalação separada do regtest, sem carteira e sem exposição RPC; iniciar `bitcoind`, aguardar `initialblockdownload=false`, sincronização de blocos e cabeçalhos, genesis mainnet correto, disco livre e ponta recente. Registrar somente diagnóstico não sensível.
5. **Lightning real.** Iniciar `lightningd` em `network=bitcoin` com identidade persistente; instalar CLNRest com HTTPS verificável e Rune restrita aos métodos do projeto. Não usar socket administrativo no cartório. **Não financiar canal automaticamente.** Abrir canais e adquirir liquidez inbound requer decisão e fundos autorizados do operador. Uma abertura própria comum fornece saída, não garante capacidade de recebimento. Não existe retorno garantido ao rotear pagamentos.
6. **Segredos e continuidade.** Seguir `docs/mainnet.md`: chave Ed25519 criptografada, senha e chave de backup fora do repositório, banco SQLite em disco persistente, snapshots autenticados e exportação externa em mídia/conta independente. Testar restauração em destino novo, não apenas criação do arquivo. Fazer plano de recuperação **separado** da carteira/canais Lightning: `hsm_secret` ou mnemonic, `emergency.recover`, replica adequada do estado de canais; snapshots antigos de banco Lightning podem provocar perda de fundos. Referência https://docs.corelightning.org/docs/backup .
7. **Workers e monitoramento.** Configurar worker systemd `deploy/mainnet/cartorio-worker.service`. Instalar também `cartorio-healthcheck.service` + timer para diagnóstico periódico. Um código de saída não zero deve gerar alerta via monitor externo (não incluso). Monitorar saldo/liquidez, sincronia, disco, processo, faturas expiradas, backup externo e capacidade de restauração.
8. **Teste operacional sem cobrar.** Manter `allow_mainnet_invoices=false`. Executar, como usuário isolado `cartorio`:
   ```bash
   /opt/cartorio/.venv/bin/python -m cartorio_documentos --config /etc/cartorio/config.json init
   /opt/cartorio/.venv/bin/python -m cartorio_documentos --config /etc/cartorio/config.json backup
   /opt/cartorio/.venv/bin/python -m cartorio_documentos --config /etc/cartorio/config.json work --once
   /opt/cartorio/.venv/bin/python -m cartorio_documentos --config /etc/cartorio/config.json doctor
   ```
   Confirmar todos os checks OK e que `mainnet_invoices_enabled=false`. Validar `restore` em diretório novo, comparar fingerprint e comprovantes, e repetir teste após reinicializar o servidor.
9. **Teste financeiro só com autorização expressa.** Registrar um documento **sintético**; combinar limite exato em satoshis, riscos e fonte de liquidez. Após prova de backups e verificação de saldo/canais, autorizar expressamente habilitação temporária de emissão, criar fatura pequena, pagar de carteira externa controlada pelo operador, conferir recebimento, fatura, preimagem e comprovante. Exportar uma prova OTS; conferir com Bitcoin Core mainnet e seis confirmações após a ancoragem. **Não movimentar BTC nem alterar o interruptor de cobrança antecipadamente.**
10. **Produção comercial.** Revisar privacidade e aspectos jurídicos: o sistema registra integridade/existência e pode cobrar por este serviço, sem atestar identidade/autoria nem agir como cartório com fé pública, custodiante, intermediador obrigatório ou autoridade sobre transações Bitcoin. Realizar revisão externa de segurança e política de incidentes antes de oferecer a terceiros.

## Condições de NÃO liberar

- Ausência de servidor próprio configurado e acessível; só GitHub/Codespaces.
- Backup/restore externo não verificado ou `hsm_secret`/canais sem plano.
- RPC/CLNRest exposto, chave/Rune divulgada, node ID divergente ou `doctor` falhando.
- Zero liquidez de entrada ou insuficiência para valor de fatura; uptime não monitorado.
- Tarifa não definida, operação financeira não aprovada ou teste mainnet não executado.

**Estado desta revisão:** CI/regtest aprovados antes desta etapa; host de produção ainda não vinculado. O primeiro passo externo indispensável é contratar um provedor e fornecer acesso administrativo seguro **por um mecanismo de integração autorizado**, nunca colando seed, chaves privadas ou senhas na conversa.
