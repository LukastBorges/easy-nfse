# Changelog

## [0.2.3](https://github.com/LukastBorges/easy-nfse/compare/easy-nfse-v0.2.2...easy-nfse-v0.2.3) (2026-10-23)


### Correções

* **desktop:** desbloquear DLLs do pythonnet e cair para o navegador se a janela falhar ([e162756](https://github.com/LukastBorges/easy-nfse/commit/e1627565b9991d820329e42cc834655e48958a52))
* **desktop:** desbloquear DLLs do pythonnet e cair para o navegador se a janela falhar ([4fd19dd](https://github.com/LukastBorges/easy-nfse/commit/4fd19ddc72323baad44a5493b97607c69e9eeb47))

## [0.2.2](https://github.com/LukastBorges/easy-nfse/compare/easy-nfse-v0.2.1...easy-nfse-v0.2.2) (2026-10-11)


### Correções

* **ibge:** não quebrar quando a API do IBGE responde algo inesperado ([8ac909c](https://github.com/LukastBorges/easy-nfse/commit/8ac909c8293949f2ec18d3b935f70cd1c868f757))

## [0.2.1](https://github.com/LukastBorges/easy-nfse/compare/easy-nfse-v0.2.0...easy-nfse-v0.2.1) (2026-10-11)


### Correções

* ler e gravar arquivos de texto em UTF-8 em qualquer sistema ([294d01d](https://github.com/LukastBorges/easy-nfse/commit/294d01dfecd6245aa372f7f06c3d25dffee9524a))


### Documentação

* **agents:** registrar encoding UTF-8 e o fluxo de releases imutáveis ([a1aff04](https://github.com/LukastBorges/easy-nfse/commit/a1aff046cc0696620b041621c96df8a5e3ebe061))


### Build e dependências

* sincronizar a versão do projeto no uv.lock (0.2.0) ([459fbb1](https://github.com/LukastBorges/easy-nfse/commit/459fbb1e2ee3a37e6311fcec0045edd529cca0fd))

## [0.2.0](https://github.com/LukastBorges/easy-nfse/compare/easy-nfse-v0.1.0...easy-nfse-v0.2.0) (2026-10-11)


### Funcionalidades

* **assinatura:** assinar a DPS com certificado A1 e preparar mTLS ([be7eb21](https://github.com/LukastBorges/easy-nfse/commit/be7eb213eaa34ec7e1fe98d8f0d1601d2829a63b))
* **danfse:** gerar o PDF DANFSe v2.0 conforme a NT 008/2026 ([8ac2f6f](https://github.com/LukastBorges/easy-nfse/commit/8ac2f6ff8defcaaa1bd2b4f059f72afa3f3d72e2))
* **desktop:** executar como aplicativo com janela nativa ([4cbe8e6](https://github.com/LukastBorges/easy-nfse/commit/4cbe8e6a4cac08a0ed1c2f8b9e4ca348c60c3361))
* **dps:** montar e validar a DPS no leiaute v1.01 ([9c153e8](https://github.com/LukastBorges/easy-nfse/commit/9c153e8389cc81b3c798460e66cd8c273165f353))
* **importador:** criar templates a partir do PDF ou XML de uma nota ([fa840b1](https://github.com/LukastBorges/easy-nfse/commit/fa840b14956ee1fdaeaba529467fd43c35e32860))
* **ptax:** consultar cotação PTAX para exportação de serviço ([8c28303](https://github.com/LukastBorges/easy-nfse/commit/8c28303a9c35161ca0bc35b668cccfe450662bd5))
* **sefin:** adicionar cliente da API da Sefin Nacional ([7b69f89](https://github.com/LukastBorges/easy-nfse/commit/7b69f89bd8a10168f72451adc2e6642711f30e0b))
* **storage:** persistir configuração, templates e emissões em JSON ([0faece8](https://github.com/LukastBorges/easy-nfse/commit/0faece8afa0c07f17db7e967b940589caa82cd3a))
* **ui:** adicionar interface web para importar, revisar e emitir notas ([c997fd2](https://github.com/LukastBorges/easy-nfse/commit/c997fd23ee914a0b32786b5180d2c4ca75a97648))
* **ui:** adicionar logo, favicon e ícone de atalho ([c64467a](https://github.com/LukastBorges/easy-nfse/commit/c64467ae69f7c6d9a92ec4f83a08319c77be5fcd))
* **xsd:** adicionar esquemas XSD oficiais da NFS-e v1.01 ([2edb395](https://github.com/LukastBorges/easy-nfse/commit/2edb3955c841a6e15334ff282b6f550429e85871))


### Documentação

* adicionar capturas da tela inicial nos temas claro e escuro ([26ad0c9](https://github.com/LukastBorges/easy-nfse/commit/26ad0c99c697b1daca38db41f221bd40088e34f2))
* **agents:** adicionar instruções para agentes de código ([7e7c62e](https://github.com/LukastBorges/easy-nfse/commit/7e7c62ec7ab16be1dd9f41c3c4fc07d86c15013e))
* descrever uso, configuração e funcionamento no README ([49408c6](https://github.com/LukastBorges/easy-nfse/commit/49408c6d3329089a136887d886ccc11b6793dd33))
* documentar o app para macOS e Windows e o fluxo de releases ([85ab9e2](https://github.com/LukastBorges/easy-nfse/commit/85ab9e204dd06b5ff5a2baba8ea5ea52e5c0ace7))
* documentar o monitor da documentação oficial da NFS-e ([739ea6b](https://github.com/LukastBorges/easy-nfse/commit/739ea6bd4e16352f8864d1674b6b57b953a33b64))
* revisar o README e incluir requisitos, instalação e segurança ([9f5943f](https://github.com/LukastBorges/easy-nfse/commit/9f5943ffcb54b909c5cd61d2e10b99312d1ded09))


### Build e dependências

* inicializar projeto Python com uv ([f90a26c](https://github.com/LukastBorges/easy-nfse/commit/f90a26c008a9488527cf3f93605a6e32a64fe75b))
* **pyinstaller:** empacotar o app para macOS e Windows ([56eed4d](https://github.com/LukastBorges/easy-nfse/commit/56eed4d72f4d3bef8bf11773bf6edbffea5cc27f))
