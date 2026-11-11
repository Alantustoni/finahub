"""
conferir_compras.py — Bate "pasta COMPRAS do Outlook × planilha NOTAS - COMPRAS".

Por que existe: a automação (Power Automate + Office Script) pode perder notas
sem ninguém perceber — o e-mail de 06/10/2026 nem disparou o fluxo e um e-mail
de 15/10 com 243 NFs foi pulado. Este bate pega QUALQUER nota que ficou de
fora, inclusive quando o fluxo não rodou.

Como funciona:
  1. Lê (SÓ LEITURA) os e-mails da pasta COMPRAS do Outlook deste computador,
     dos remetentes configurados, nos últimos N dias. Usa o Outlook via
     PowerShell/COM (não precisa de pywin32).
  2. Extrai as notas de cada e-mail: a tabela EMPRESA | FOR | NOME | AF |
     VENCIMENTO | NF; sem tabela, a "NF 12345" do assunto (como o script v1.5).
  3. Compara com a aba "Notas recebidas": pelo ID do e-mail e, para não acusar
     reenvio, pela chave EMPRESA|FOR:x|NF:y.
  4. As que faltam podem ser incluídas na tabela tbNotas pelo próprio Excel
     (com backup antes) — ver incluir_na_planilha().
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple


# ====================================================================== #
# Texto / NF                                                              #
# ====================================================================== #
def _sa(s) -> str:
    s = "" if s is None else str(s)
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").upper().strip()


def tokens_nf(nf) -> Set[str]:
    """'630/625/624' → {630,625,624}; '19830/' → {19830}; '0001234' → {1234}."""
    out = set()
    for parte in re.split(r"[/;,\s\-]+", str(nf or "")):
        dig = re.sub(r"\D", "", parte).lstrip("0")
        if dig:
            out.add(dig)
    return out


def _nf_limpa(nf: str) -> str:
    return re.sub(r"\s+", " ", str(nf or "")).strip().strip("/-").strip()


# ====================================================================== #
# HTML → tabelas                                                          #
# ====================================================================== #
class _Tabelas(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabelas: List[List[List[str]]] = []
        self._pilha: List[List[List[str]]] = []
        self._linha: Optional[List[str]] = None
        self._cel: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            t: List[List[str]] = []
            self._pilha.append(t)
            self.tabelas.append(t)
        elif tag == "tr" and self._pilha:
            self._linha = []
            self._pilha[-1].append(self._linha)
        elif tag in ("td", "th") and self._linha is not None:
            self._cel = []
        elif tag == "br" and self._cel is not None:
            self._cel.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cel is not None and self._linha is not None:
            self._linha.append(re.sub(r"\s+", " ", "".join(self._cel)).strip())
            self._cel = None
        elif tag == "table" and self._pilha:
            self._pilha.pop()
            self._linha = None

    def handle_data(self, data):
        if self._cel is not None:
            self._cel.append(data)


_CAMPOS = {
    "EMPRESA": "empresa", "FOR": "codigo", "COD": "codigo", "CODIGO": "codigo",
    "NOME": "fornecedor", "FORNECEDOR": "fornecedor", "AF": "af", "AF / PEDIDO": "af",
    "PEDIDO": "af", "VENCIMENTO": "vencimento", "VENC": "vencimento", "NF": "nf",
    "NOTA": "nf", "NOTA FISCAL": "nf",
}


@dataclass
class NotaEmail:
    nf: str
    empresa: str = ""
    fornecedor: str = ""
    codigo: str = ""
    af: str = ""
    vencimento: str = ""
    origem: str = "TABELA"          # TABELA | ASSUNTO


def notas_da_tabela(html: str, empresas: Sequence[str]) -> List[NotaEmail]:
    p = _Tabelas()
    try:
        p.feed(html or "")
    except Exception:                                   # noqa: BLE001
        return []
    emp_up = [_sa(e) for e in empresas]
    out: List[NotaEmail] = []
    for tab in p.tabelas:
        mapa: Optional[Dict[str, int]] = None
        for linha in tab:
            up = [_sa(c) for c in linha]
            cand = {_CAMPOS[c]: i for i, c in enumerate(up) if c in _CAMPOS}
            if mapa is None:
                if "nf" in cand and ("fornecedor" in cand or "empresa" in cand):
                    mapa = cand
                continue
            if len(linha) <= mapa["nf"]:
                continue
            junto = " ".join(up)
            if emp_up and not any(e in junto for e in emp_up):
                continue
            get = lambda k: linha[mapa[k]].strip() if k in mapa and mapa[k] < len(linha) else ""
            nf = _nf_limpa(get("nf"))
            if not tokens_nf(nf):
                continue
            out.append(NotaEmail(nf=nf, empresa=_sa(get("empresa")), fornecedor=get("fornecedor"),
                                 codigo=get("codigo"), af=get("af"), vencimento=get("vencimento")))
    return out


_RE_NF_ASSUNTO = re.compile(r"\b(?:NF|NOTA FISCAL)\s*[:#-]?\s*(\d+(?:\s*/\s*\d+)*)(?![\dA-Za-z])", re.I)
_RE_PREFIXO = re.compile(r"^(?:(?:ENC|RES|RE|FW|FWD)(?:\s*\[\d+\])?\s*[:：]\s*)+", re.I)


def nota_do_assunto(assunto: str, empresas: Sequence[str]) -> Optional[NotaEmail]:
    """Mesma regra do script v1.5: sem tabela, 'NF 12345' no assunto; devolução não."""
    sub = _RE_PREFIXO.sub("", assunto or "").strip()
    m = _RE_NF_ASSUNTO.search(sub)
    if not m or re.search(r"DEVOLU[CÇ][AÃ]O", sub, re.I):
        return None
    nf = re.sub(r"\s+", "", m.group(1))
    af = re.search(r"\bAF\s*[:#-]?\s*(\d+(?:\s*/\s*\d+)*)", sub, re.I)
    padrao_emp = "|".join(re.escape(e) for e in empresas) or "$^"
    emp = re.search(r"\bX\s+(" + padrao_emp + r")\b", _sa(sub))
    forn = re.sub(r"\b(?:NF|NOTA FISCAL)\s*[:#-]?\s*\d+(?:\s*/\s*\d+)*", " ", sub, flags=re.I)
    forn = re.sub(r"\bAF\s*[:#-]?\s*\d+(?:\s*/\s*\d+)*", " ", forn, flags=re.I)
    forn = re.sub(r"\bX\s+(?:" + padrao_emp + r")\b.*$", " ", forn, flags=re.I)
    forn = re.sub(r"^\s*(?:PAGAMENTO|DESCONTO|ENVIO DE NOTA FISCAL)\s*[:\-]?\s*", "", forn, flags=re.I)
    forn = re.sub(r"\s+", " ", forn).strip(" -/:|")
    return NotaEmail(nf=nf, empresa=emp.group(1) if emp else "", fornecedor=forn,
                     af=af.group(1).replace(" ", "") if af else "", origem="ASSUNTO")


# ====================================================================== #
# Outlook (somente leitura, via PowerShell/COM)                           #
# ====================================================================== #
_PS_LER = r"""
param([string]$conta, [string]$pasta, [string]$desde, [string]$remetentes, [string]$saida)
$ErrorActionPreference = 'Stop'
$ol = New-Object -ComObject Outlook.Application
$ns = $ol.GetNamespace("MAPI")
$raiz = $ns.Folders | ? { $_.Name -eq $conta }
if (-not $raiz) { throw "Conta '$conta' não encontrada no Outlook." }
$f = $raiz.Folders | ? { $_.Name -eq $pasta }
if (-not $f) { throw "Pasta '$pasta' não encontrada na conta '$conta'." }
$rems = $remetentes.ToLower().Split(';') | ? { $_ }
$its = $f.Items.Restrict("@SQL=urn:schemas:httpmail:datereceived >= '$desde 00:00'")
$lista = New-Object System.Collections.Generic.List[object]
foreach ($m in $its) {
  if ($m.Class -ne 43) { continue }
  $smtp = $m.SenderEmailAddress
  if ($m.SenderEmailType -eq "EX") { try { $smtp = $m.Sender.GetExchangeUser().PrimarySmtpAddress } catch {} }
  $smtp = ("" + $smtp).ToLower()
  if ($rems.Count -and -not ($rems -contains $smtp)) { continue }
  $mid = ""; try { $mid = $m.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x1035001F") } catch {}
  $lista.Add([pscustomobject]@{ recebido = $m.ReceivedTime.ToString("yyyy-MM-dd HH:mm"); remetente = $smtp;
    assunto = "" + $m.Subject; mid = "" + $mid; html = "" + $m.HTMLBody })
}
$json = ConvertTo-Json -InputObject @($lista.ToArray()) -Depth 3
[IO.File]::WriteAllText($saida, $json, (New-Object Text.UTF8Encoding $false))
"""


@dataclass
class EmailCompras:
    recebido: str
    remetente: str
    assunto: str
    mid: str
    html: str = ""


def _rodar_ps(script: str, *args: str, timeout: int = 900) -> str:
    with tempfile.TemporaryDirectory() as d:
        ps1 = Path(d) / "alan.ps1"
        ps1.write_text(script, encoding="utf-8-sig")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            msg = (r.stderr or r.stdout or "").strip().splitlines()
            raise RuntimeError(next((l for l in msg if l.strip()), "falha no PowerShell"))
        return r.stdout


def ler_outlook(conta: str, pasta: str, remetentes: Sequence[str], desde: datetime) -> List[EmailCompras]:
    with tempfile.TemporaryDirectory() as d:
        saida = Path(d) / "emails.json"
        _rodar_ps(_PS_LER, conta, pasta, desde.strftime("%Y-%m-%d"),
                  ";".join(r.strip().lower() for r in remetentes if r.strip()), str(saida))
        dados = json.loads(saida.read_text(encoding="utf-8")) if saida.exists() else []
    if isinstance(dados, dict):
        dados = [dados]
    return [EmailCompras(**{k: (x.get(k) or "") for k in ("recebido", "remetente", "assunto", "mid", "html")})
            for x in dados]


# ====================================================================== #
# Planilha                                                                #
# ====================================================================== #
def _norm_id(s) -> str:
    return str(s or "").strip().strip("<>").lower()


@dataclass
class Planilha:
    nfs_por_email: Dict[str, Set[str]] = field(default_factory=dict)
    chaves: Set[str] = field(default_factory=set)
    total_linhas: int = 0
    emails_registrados: Set[str] = field(default_factory=set)   # aba Emails


def chave(empresa: str, codigo: str, nf: str) -> str:
    return f"{_sa(empresa)}|FOR:{str(codigo or '').strip()}|NF:{_nf_limpa(nf)}"


def ler_planilha(path: Path) -> Planilha:
    from .pensoes import ler_xlsx
    abas = ler_xlsx(Path(path))
    nome = next((k for k in abas if "RECEBID" in _sa(k)), None)
    if nome is None:
        raise ValueError("a planilha não tem a aba 'Notas recebidas'.")
    linhas = abas[nome]
    hi = next((i for i, r in enumerate(linhas[:40])
               if "NF" in {_sa(v) for v in r.values()} and "ID_EMAIL" in {_sa(v) for v in r.values()}), None)
    if hi is None:
        raise ValueError("não achei o cabeçalho (NF / ID_Email) na aba 'Notas recebidas'.")
    cab = {_sa(v): c for c, v in linhas[hi].items()}
    c_nf, c_id, c_ch = cab.get("NF"), cab.get("ID_EMAIL"), cab.get("CHAVE_PROVISORIA")
    p = Planilha()
    for r in linhas[hi + 1:]:
        if not r:
            continue
        p.total_linhas += 1
        mid = _norm_id(r.get(c_id))
        p.nfs_por_email.setdefault(mid, set()).update(tokens_nf(r.get(c_nf)))
        if c_ch is not None and r.get(c_ch):
            ch = str(r.get(c_ch)).strip()
            p.chaves.add(ch)
            # chave com NF composta '29231/1139' também vale por NF individual
            m = re.match(r"^(.*\|NF:)(.*)$", ch)
            if m:
                for t in tokens_nf(m.group(2)):
                    p.chaves.add(m.group(1) + t)
    # aba Emails: e-mails que a automação registrou (mesmo sem gerar nota)
    aba_em = next((k for k in abas if _sa(k) == "EMAILS"), None)
    if aba_em:
        le = abas[aba_em]
        he = next((i for i, r in enumerate(le[:40]) if "ID_EMAIL" in {_sa(v) for v in r.values()}), None)
        if he is not None:
            ce = {_sa(v): c for c, v in le[he].items()}
            for col in ("ID_EMAIL", "INTERNET_MESSAGE_ID"):
                c = ce.get(col)
                if c is not None:
                    p.emails_registrados |= {_norm_id(r.get(c)) for r in le[he + 1:] if r and r.get(c)}
    return p


# ====================================================================== #
# Bate                                                                    #
# ====================================================================== #
@dataclass
class Faltando:
    recebido: str
    remetente: str
    assunto: str
    mid: str
    nf: str
    empresa: str
    fornecedor: str
    codigo: str
    af: str
    vencimento: str
    origem: str
    motivo: str


@dataclass
class ResultadoConferencia:
    emails: int = 0
    emails_fora: int = 0             # e-mails que nem estão na planilha
    notas_email: int = 0
    notas_ok: int = 0
    faltando: List[Faltando] = field(default_factory=list)
    sem_nota: List[Tuple[str, str]] = field(default_factory=list)   # (recebido, assunto)
    desde: str = ""

    @property
    def tudo_certo(self) -> bool:
        return not self.faltando


def conferir(emails: Sequence[EmailCompras], planilha: Planilha,
             empresas: Sequence[str] = ("ALFAMETAL", "BETAVIARIA")) -> ResultadoConferencia:
    r = ResultadoConferencia(emails=len(emails))
    for e in sorted(emails, key=lambda x: x.recebido):
        notas = notas_da_tabela(e.html, empresas)
        if not notas:
            na = nota_do_assunto(e.assunto, empresas)
            notas = [na] if na else []
        if not notas:
            r.sem_nota.append((e.recebido, e.assunto))
            continue
        mid = _norm_id(e.mid)
        registrado = mid in planilha.nfs_por_email
        if not registrado:
            r.emails_fora += 1
        na_planilha = planilha.nfs_por_email.get(mid, set())
        for n in notas:
            r.notas_email += 1
            toks = tokens_nf(n.nf)
            if toks and toks <= na_planilha:
                r.notas_ok += 1
                continue
            # reenvio: a mesma nota já entrou por outro e-mail
            if n.codigo and all(chave(n.empresa, n.codigo, t) in planilha.chaves for t in toks):
                r.notas_ok += 1
                continue
            if registrado:
                motivo = "nota não registrada (e-mail entrou incompleto)"
            elif mid in planilha.emails_registrados:
                motivo = "e-mail registrado, mas sem nota (formato não reconhecido)"
            else:
                motivo = "e-mail não registrado pela automação"
            r.faltando.append(Faltando(e.recebido, e.remetente, e.assunto, e.mid, n.nf, n.empresa,
                                       n.fornecedor, n.codigo, n.af, n.vencimento, n.origem, motivo))
    return r


def executar(cfg: dict, planilha_path: Path, dias: int) -> ResultadoConferencia:
    """Etapa pesada (thread): lê Outlook + planilha e confere."""
    from datetime import timedelta
    desde = datetime.now() - timedelta(days=max(1, int(dias)))
    # nunca antes do início da automação (e-mails anteriores nunca foram para a planilha)
    inicio = str(cfg.get("inicio_automacao", "") or "")
    try:
        minimo = datetime.strptime(inicio[:10], "%Y-%m-%d")
        desde = max(desde, minimo)
    except ValueError:
        pass
    emails = ler_outlook(cfg.get("conta", ""), cfg.get("pasta", "COMPRAS"),
                         cfg.get("remetentes", []), desde)
    res = conferir(emails, ler_planilha(planilha_path), cfg.get("empresas", ["ALFAMETAL", "BETAVIARIA"]))
    res.desde = desde.strftime("%d/%m/%Y")
    return res


# ====================================================================== #
# Inclusão na planilha (pelo Excel, como se fosse digitado)              #
# ====================================================================== #
_PS_INCLUIR = r"""
param([string]$arquivo, [string]$dados, [string]$backup)
$ErrorActionPreference = 'Stop'
$itens = Get-Content $dados -Raw -Encoding UTF8 | ConvertFrom-Json
$ci = [Globalization.CultureInfo]::InvariantCulture
try { $xl = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application") } catch { $xl = $null }
$abriu = $false; $wb = $null
$nomeArq = [IO.Path]::GetFileName($arquivo)
if ($xl) { $wb = $xl.Workbooks | ? { $_.Name -eq $nomeArq } | Select -First 1 }
if (-not $wb) {
  # não está aberta: usa um Excel separado e escondido (não aparece para o usuário)
  $xl = New-Object -ComObject Excel.Application
  $xl.Visible = $false; $xl.DisplayAlerts = $false
  $wb = $xl.Workbooks.Open($arquivo); $abriu = $true
}
if ($backup) { $wb.SaveCopyAs($backup) }
$ws = $wb.Worksheets.Item("Notas recebidas")
$lo = $ws.ListObjects.Item("tbNotas")
$col = @{}; $i = 1; foreach ($c in $lo.ListColumns) { $col[$c.Name] = $i; $i++ }
$ncol = $lo.ListColumns.Count
$n0 = $lo.ListRows.Count
$existe = @{}
if ($n0 -gt 0) {
  $ch = $lo.ListColumns.Item("Chave_Provisoria").DataBodyRange.Value2
  for ($k = 1; $k -le $n0; $k++) { $existe["" + $ch[$k,1]] = 1 }
}
$grupos = @($itens | Group-Object recebido | Sort-Object Name)   # mais antigo primeiro
$inseridas = 0; $puladas = 0
foreach ($g in $grupos) {
  $novos = @()
  foreach ($it in $g.Group) {
    $chv = "$($it.empresa)|FOR:$($it.codigo)|NF:$($it.nf)"
    if ($existe.ContainsKey($chv)) { $puladas++; continue }
    $existe[$chv] = 1; $novos += $it
  }
  if ($novos.Count -eq 0) { continue }
  $oa = ([datetime]::ParseExact($g.Name, "yyyy-MM-dd HH:mm", $ci)).ToOADate()
  $n = $lo.ListRows.Count
  $pos = 1
  if ($n -gt 0) {
    $rec = $lo.ListColumns.Item("Recebido em").DataBodyRange.Value2
    while ($pos -le $n -and [double]$rec[$pos,1] -gt $oa) { $pos++ }
  }
  $q = $novos.Count
  if ($pos -le $n) { $lo.ListRows.Item($pos).Range.Resize($q).Insert(-4121) | Out-Null }
  else { for ($k = 0; $k -lt $q; $k++) { $lo.ListRows.Add() | Out-Null } }
  $arr = New-Object 'object[,]' $q, $ncol
  for ($k = 0; $k -lt $q; $k++) {
    $it = $novos[$k]
    $dt = [datetime]::MinValue
    $venc = if ([datetime]::TryParseExact("" + $it.vencimento, [string[]]@("dd/MM/yyyy","d/M/yyyy"), $ci, [Globalization.DateTimeStyles]::None, [ref]$dt)) { $dt.ToOADate() } else { "" + $it.vencimento }
    $vals = @{
      "NF" = "" + $it.nf; "Empresa" = "" + $it.empresa; "Fornecedor" = "" + $it.fornecedor; "FOR" = "" + $it.codigo
      "AF / Pedido" = "" + $it.af; "Vencimento" = $venc; "Comunicação" = $(if ($it.origem -eq "ASSUNTO") { "NF lida do assunto — conferir" } else { "Envio informado" })
      "Recebido em" = $oa; "Conferencia" = "Aguardando conferência"; "Possivel_Vinculo" = "Não localizado nesta base"
      "Observacoes" = "Dados de origem: [`"$($it.empresa)`",`"$($it.codigo)`",`"$($it.fornecedor)`",`"$($it.af)`",`"$($it.vencimento)`",`"$($it.nf)`"] | ALAN-L$($k+1) | Referência de e-mail; documento fiscal não verificado. | Incluída pelo ALAN (Conferir Compras) em $(Get-Date -Format 'dd/MM/yyyy') — $($it.motivo)."
      "ID_Email" = "" + $it.mid; "ID_Registro" = "$($it.mid)|V13|ALAN-L$($k+1)"; "Chave_Provisoria" = "$($it.empresa)|FOR:$($it.codigo)|NF:$($it.nf)"
    }
    foreach ($nome in $vals.Keys) { if ($col.ContainsKey($nome)) { $arr[$k, ($col[$nome]-1)] = $vals[$nome] } }
  }
  $lo.DataBodyRange.Rows.Item($pos).Resize($q).Value2 = $arr
  $inseridas += $q
}
if ($abriu) {
  $wb.Save(); $wb.Close($false); $xl.Quit()
  # solta as referências COM — senão o Excel escondido fica preso na memória
  foreach ($o in @($lo, $ws, $wb, $xl)) { if ($o) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($o) } }
  [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
"$inseridas;$puladas"
"""


def incluir_na_planilha(planilha_path: Path, faltando: Sequence[Faltando],
                        pasta_backup: Optional[Path] = None) -> Tuple[int, int, str]:
    """
    Insere as notas em 'Notas recebidas' (tabela tbNotas) pelo Excel: se a
    planilha já estiver aberta, usa a mesma janela (salvamento automático do
    OneDrive); senão abre escondido, salva e fecha. Faz uma cópia de backup
    antes. Devolve (inseridas, puladas_por_ja_existir, caminho_backup).
    """
    if not faltando:
        return 0, 0, ""
    backup = ""
    if pasta_backup:
        Path(pasta_backup).mkdir(parents=True, exist_ok=True)
        backup = str(Path(pasta_backup) / f"NOTAS - COMPRAS - backup {datetime.now():%Y%m%d_%H%M%S}.xlsx")
    with tempfile.TemporaryDirectory() as d:
        dados = Path(d) / "faltando.json"
        dados.write_text(json.dumps([asdict(f) for f in faltando], ensure_ascii=False), encoding="utf-8")
        saida = _rodar_ps(_PS_INCLUIR, str(Path(planilha_path)), str(dados), backup).strip().splitlines()
    ult = saida[-1] if saida else "0;0"
    ins, pul = (int(x) for x in ult.split(";")[:2])
    return ins, pul, backup
