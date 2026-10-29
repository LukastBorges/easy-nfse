"""Modelos persistidos (templates, configuração, emissões)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Ambiente = Literal["1", "2"]  # 1 = Produção, 2 = Produção restrita (homologação)


class Endereco(BaseModel):
    pais: str = ""  # ISO2; vazio ou "BR" = endereço nacional
    # nacional
    cep: str = ""
    cod_municipio: str = ""
    municipio: str = ""  # "Porto Alegre/RS" (apenas exibição / resolução do código IBGE)
    # exterior
    cod_postal: str = ""
    cidade: str = ""
    estado_prov: str = ""
    # ambos
    logradouro: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""

    @property
    def exterior(self) -> bool:
        return bool(self.pais) and self.pais != "BR"

    def preenchido(self) -> bool:
        return any([self.cep, self.cod_postal, self.cidade, self.logradouro, self.numero, self.bairro])

    def completo(self) -> bool:
        if self.exterior:
            return all([self.cod_postal, self.cidade, self.estado_prov, self.logradouro])
        return all([self.cep, self.cod_municipio, self.logradouro, self.numero, self.bairro])


class Prestador(BaseModel):
    tipo_doc: Literal["CNPJ", "CPF"] = "CNPJ"
    documento: str = ""
    nome: str = ""  # só exibição: não vai na DPS quando o prestador é o emitente (E0121)
    im: str = ""
    fone: str = ""
    email: str = ""
    cod_municipio: str = ""  # cLocEmi
    municipio: str = ""
    op_simp_nac: Literal["1", "2", "3"] = "1"
    reg_ap_trib_sn: str = ""  # só para ME/EPP (op_simp_nac = 3)
    reg_esp_trib: str = "0"


class Tomador(BaseModel):
    tipo_doc: Literal["CNPJ", "CPF", "NIF", ""] = "CPF"  # NIF = tomador do exterior
    documento: str = ""
    c_nao_nif: str = ""  # motivo de não informar o NIF (1 = dispensado, 2 = não exigência)
    nome: str = ""
    im: str = ""
    fone: str = ""
    email: str = ""
    endereco: Endereco = Field(default_factory=Endereco)


class Servico(BaseModel):
    c_trib_nac: str = ""
    c_trib_nac_desc: str = ""
    c_trib_mun: str = ""
    c_nbs: str = ""
    descricao: str = ""
    cod_municipio_prestacao: str = ""
    municipio_prestacao: str = ""
    pais_prestacao: str = ""  # ISO2, só quando o serviço é prestado no exterior


class Tributacao(BaseModel):
    trib_issqn: Literal["1", "2", "3", "4"] = "1"
    pais_resultado: str = ""  # cPaisResult (exportação com prestação no Brasil)
    tp_imunidade: str = ""
    tp_ret_issqn: Literal["1", "2", "3"] = "1"
    p_aliq: str = ""  # vazio = não informar (o sistema usa a parametrização do município)
    p_tot_trib_sn: str = ""  # obrigatório para ME/EPP (indTotTrib não é permitido)


class ComercioExterior(BaseModel):
    """Grupo comExt: obrigatório para tomador no exterior / exportação (E0330)."""

    md_prestacao: str = "1"  # 1 = transfronteiriço
    vinc_prest: str = "0"  # 0 = sem vínculo
    tp_moeda: str = "220"  # código BACEN (220 = USD)
    mec_af_comex_p: str = "01"  # 01 = nenhum
    mec_af_comex_t: str = "01"
    mov_temp_bens: str = "1"  # 1 = não
    n_di: str = ""
    n_re: str = ""
    mdic: str = "0"


class Origem(BaseModel):
    tipo: Literal["xml", "pdf", "chave", "manual"] = "manual"
    arquivo: str = ""
    chave_acesso: str = ""
    numero_nfse: str = ""
    competencia: str = ""
    valor: str = ""
    valor_moeda: str = ""
    aliquota_original: str = ""


class Template(BaseModel):
    id: str
    nome: str
    criado_em: datetime = Field(default_factory=datetime.now)
    atualizado_em: datetime = Field(default_factory=datetime.now)
    prestador: Prestador = Field(default_factory=Prestador)
    tomador: Tomador | None = Field(default_factory=Tomador)
    servico: Servico = Field(default_factory=Servico)
    tributacao: Tributacao = Field(default_factory=Tributacao)
    com_ext: ComercioExterior = Field(default_factory=ComercioExterior)
    origem: Origem = Field(default_factory=Origem)
    certificado_id: str = ""  # vazio = automático: o certificado do CNPJ/CPF do prestador
    ultimo_valor: str = ""
    ultimo_valor_moeda: str = ""
    avisos: list[str] = Field(default_factory=list)

    @property
    def tomador_exterior(self) -> bool:
        return bool(self.tomador and self.tomador.tipo_doc == "NIF")

    @property
    def exige_com_ext(self) -> bool:
        """Exportação de serviço: tomador no exterior, prestação no exterior ou tribISSQN = 3."""
        return self.tomador_exterior or bool(self.servico.pais_prestacao) or self.tributacao.trib_issqn == "3"


class CertificadoSalvo(BaseModel):
    """Certificado A1 guardado em `certificados/<id>.pfx`; a senha fica aqui, no config.json."""

    id: str
    arquivo: str = ""  # nome do arquivo enviado (só exibição)
    senha: str = ""
    adicionado_em: datetime = Field(default_factory=datetime.now)
    # lidos do certificado ao salvar, para as páginas não precisarem abrir (decifrar) cada .pfx
    titular: str = ""
    documento: str = ""
    validade: datetime | None = None
    impressao: str = ""  # SHA-256 do certificado (reenvio do mesmo arquivo substitui em vez de duplicar)


class Config(BaseModel):
    ambiente: Ambiente = "2"
    serie: str = "1"
    # último nDPS usado, por ambiente + documento do prestador + série
    numeracao: dict[str, int] = Field(default_factory=dict)
    certificados: list[CertificadoSalvo] = Field(default_factory=list)
    certificado_senha: str = ""  # legado: senha do certificado único (migrada para `certificados`)
    verificar_tls: bool = True
    verificar_atualizacoes: bool = True  # consulta as releases do GitHub e baixa a versão nova (ver atualizacao.py)

    @staticmethod
    def chave_numeracao(ambiente: str, documento: str, serie: str) -> str:
        return f"{ambiente}|{documento}|{int(serie)}"


class Emissao(BaseModel):
    chave_acesso: str
    numero_nfse: str = ""
    id_dps: str
    serie: str
    n_dps: int
    ambiente: Ambiente
    template_id: str
    template_nome: str
    tomador: str = ""
    valor: str
    valor_moeda: str = ""
    moeda: str = ""
    competencia: str
    emitida_em: datetime = Field(default_factory=datetime.now)
    pasta: str = ""
