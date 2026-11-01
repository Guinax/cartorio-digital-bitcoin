# Oracle Cloud Always Free: Bitcoin Core + Core Lightning (perfil econômico)

**Status: arquivos de configuração para revisão; instalação NÃO realizada.**
**Esta opção não fornece SLA financeiro nem disponibilidade garantida.**
Operar rede Bitcoin/LN não implica minerar, lucrar ou cobrar pedágio sobre terceiros.

## Cotas verificadas em 01/11/2026

Fonte oficial: https://docs.oracle.com/pt-br/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

- OCI Ampere A1, VM.Standard.A1.Flex (ARM64): 1.500 OCPU-h/mês e 9.000 GB-h/mês, equivalentes a **2 OCPUs e 12 GB RAM**, para uma instância ligada o mês inteiro, respeitando as cotas de uma conta Always Free.
- **200 GB** totais de boot + block volume. Recomenda-se **50 GB** no volume do sistema e **150 GB** em volume de dados persistente (aprox. 139 GiB). Não interpretar 200 GB como 200 GiB nem contratar volume extra fora da cota.
- 10 TB/mês de tráfego de saída incluído dentro das condições vigentes; consultar fatura/quotas e regras da região.
- A Oracle **pode recuperar VM ociosa**; recursos ARM podem estar indisponíveis na região home. Não há garantia de máquina 24/7, restaurabilidade ou recepção financeira.
- Cadastrar conta, região home, verificação de identidade e eventual cartão por conta do titular. **Não fazer upgrade para PAYG nem criar recursos pagos.** Nunca compartilhar dados de pagamento com o projeto.

## Arquitetura

- **Oracle ARM64 VM:** Bitcoin Core mainnet **podado** + Core Lightning mainnet + worker local de registro de documentos (como usuário sem privilégios).
- **Vercel/Supabase (opcionais):** interface, login e metadados sem segredos. Não publicar chaves de carteiras, `hsm_secret`, Rune ou cookie RPC, nem integrar API pública do nó antes de revisão de autenticação e segurança.
- **Offline, local e fora da conta Oracle:** backup comprovadamente recuperável da carteira/canais e chaves do cartório. Backup do banco do cartório NÃO substitui recuperação Lightning.
- Não disponibilizar RPC 8332, CLNRest 3010, banco ou SSH amplo na internet. Considerar VPN privada, firewall mínimo e autenticação por chave.

## Provisionamento manual gratuito (não há conta OCI conectada aqui)

1. Criar conta em https://www.oracle.com/br/cloud/free/ e confirmar modalidade **Always Free**, região home e disponibilidade de VM ARM.
2. VM `VM.Standard.A1.Flex` com 2 OCPUs, 12 GB RAM, imagem ARM64 `Ubuntu 24.04 LTS` **Always Free Eligible**, volume de boot 50 GB. Não habilitar cartão como autorização para ultrapassar cotas.
3. Alocar volume em blocos **até 150 GB** no mesmo domínio/região com elegibilidade Always Free. Anexar, formatar e montar permanentemente em `/var/lib/bitcoind` usando UUID e fstab, com as permissões apropriadas. Conferir `lsblk -f`, `df -h` e `findmnt /var/lib/bitcoind`. **Cuidado: formatar volume errado destrói dados.** Não executar este passo sem verificar o UUID exato.
4. Instalar Bitcoin Core e Core Lightning compatíveis com ARM64 de fontes oficiais e verificando *assinaturas*; não usar binário ou `curl | bash` de origem não confiável. Linux ARM64 é diferente de x86_64. Consulte https://bitcoincore.org/en/download/ e https://docs.corelightning.org/docs/getting-started .
5. Adaptar `bitcoin.conf.example` deste diretório para o diretório de dados e o usuário do serviço. **`prune=20000`** retém cerca de 20 GB de blocos recentes; ainda precisa baixar e validar todo o histórico na sincronização inicial e manter chainstate, mempool e logs. Não usar `txindex=1` com pruning.
6. Configurar Core Lightning na mainnet em usuário separado e storage persistente, somente depois de Bitcoin Core sincronizar. Manter `blocksonly=0`; CLN deve acompanhar a altura de blocos do Core. **Se o Core apagar blocos que o CLN não processou durante uma queda longa, a sincronização do CLN pode ficar impossibilitada de prosseguir**. Fonte https://docs.corelightning.org/docs/bitcoin-core .
7. Executar pré-diagnóstico **somente leitura** da VM após instalar ferramentas e montar o disco:

   ```bash
   python3 deploy/mainnet/host_preflight.py --data-dir /var/lib/bitcoind --min-volume-gib 120 --min-ram-gib 8 --min-free-gib 35
   ```

   A saída deve indicar `ready_for_host_setup=true` somente com todas as verificações aprovadas. Isso **não** comprova sincronização, porta alcançável, backups ou fundos recebíveis.

8. Configurar `deploy/mainnet/config.example.json` como arquivo privado no servidor e seguir `docs/mainnet.md`. O campo `allow_mainnet_invoices` fica **false**. Fazer `init`, `backup`, `work --once`, `doctor`, testar recuperação separada e monitorar as unidades systemd de readiness e worker somente quando o host estiver provisionado.
9. Conferir `bitcoin-cli getblockchaininfo`, `lightning-cli --network=bitcoin getinfo` e `doctor` até que o Core e o Lightning estejam sincronizados e o armazenamento livre seja suficiente. O `doctor` exige margem entre `pruneheight` e a altura do CLN para uma VM podada.
10. **Recebimento real não automático:** liquidez de entrada vem de canais existentes, peer ou serviços de liquidez que podem exigir BTC e/ou taxas. Só financiar canais, adquirir liquidez, gerar faturas reais e testar pagamentos de baixo valor após autorização explícita, plano de recuperação real, controle de gastos e alerta de indisponibilidade. Não há lucro garantido por manter o nó ligado.

## Regras de pausa

- VM OCI indisponível/reclamada: **não assumir que está online**; restaurar somente de backups adequados e íntegros. Cópia antiga do banco Lightning pode provocar perda de fundos.
- Crescimento de disco, falta de RAM, CLN atrasado em relação à janela de blocos podados, chaves/identidade inconsistentes: **manter novas faturas pausadas**.
- Não aproveitar scripts de restauração do cartório para restaurar carteira Lightning.
- Não expor wallet/seed, cookie RPC e Runes em GitHub, Vercel, Supabase ou chat.
- Em produção financeira pública, VPS gratuita sem SLA é inadequada para volume relevante ou custódia. Preferir validação de nó sem saldo e operação assistida pequena até avaliar disponibilidade real.

**Alternativas:** PC Linux próprio com SSD, energia e internet já existentes (custo marginal de energia/rede); Google Cloud e2-micro com disco gratuito de 30 GB é muito limitada para este projeto. Fonte: https://docs.cloud.google.com/free/docs/free-cloud-features?hl=pt-br .
