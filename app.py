# -*- coding: utf-8 -*-
from flask import Flask, render_template, jsonify, request
import xml.etree.ElementTree as ET
import os, re, unicodedata, webbrowser, threading
from datetime import datetime

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

NS = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}

# ── helpers ───────────────────────────────────────────────────────────────────

def get_json_body():
    import json as _j
    try:
        return _j.loads(request.get_data(as_text=True)) or {}
    except Exception:
        return request.get_json(force=True, silent=True) or {}

def normalizar_path(p):
    p = p.strip().strip('"').strip("'")
    p = p.replace('\\', os.sep).replace('/', os.sep)
    return p

def slugify(text):
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = text.upper()
    text = re.sub(r'[^A-Z0-9]+', '_', text)
    return text.strip('_')

def gerar_nome_sugerido(nota):
    try:
        raw = nota.get('dhEmi_raw', '')
        data_str = datetime.fromisoformat(raw[:19]).strftime('%d%m%Y') if raw else 'SEMDATA'
        tipo  = 'SAIDA' if nota.get('tpNF') == '1' else 'ENTRADA'
        emit  = slugify(nota.get('emit_nome', 'FORNECEDOR'))[:40].strip('_')
        valor = int(round(nota.get('vNF', 0)))
        return '%s_%s_%s_%s' % (data_str, tipo, emit, valor)
    except Exception:
        return None

@app.errorhandler(404)
def err404(e): return jsonify({'error': 'Rota nao encontrada'}), 404

@app.errorhandler(500)
def err500(e): return jsonify({'error': 'Erro interno: ' + str(e)}), 500

# ── parse XML ─────────────────────────────────────────────────────────────────

def parse_nfe(filepath):
    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
        root = ET.fromstring(raw)

        def find(path):
            el = root.find(path, NS)
            return el.text.strip() if el is not None and el.text else ''

        nNF     = find('.//nfe:nNF')
        dhEmi   = find('.//nfe:dhEmi')
        natOp   = find('.//nfe:natOp')
        tpNF    = find('.//nfe:tpNF')   # 0=entrada 1=saida

        emit_nome = find('.//nfe:emit/nfe:xNome')
        emit_cnpj = find('.//nfe:emit/nfe:CNPJ')
        emit_mun  = find('.//nfe:emit/nfe:enderEmit/nfe:xMun')
        emit_uf   = find('.//nfe:emit/nfe:enderEmit/nfe:UF')

        dest_nome = find('.//nfe:dest/nfe:xNome')
        dest_cnpj = find('.//nfe:dest/nfe:CNPJ') or find('.//nfe:dest/nfe:CPF')
        dest_mun  = find('.//nfe:dest/nfe:enderDest/nfe:xMun')
        dest_uf   = find('.//nfe:dest/nfe:enderDest/nfe:UF')

        vNF     = find('.//nfe:total/nfe:ICMSTot/nfe:vNF')
        vICMS   = find('.//nfe:total/nfe:ICMSTot/nfe:vICMS')
        vST     = find('.//nfe:total/nfe:ICMSTot/nfe:vST')
        vPIS    = find('.//nfe:total/nfe:ICMSTot/nfe:vPIS')
        vCOFINS = find('.//nfe:total/nfe:ICMSTot/nfe:vCOFINS')
        vProd   = find('.//nfe:total/nfe:ICMSTot/nfe:vProd')

        items = []
        for det in root.findall('.//nfe:det', NS):
            prod = det.find('nfe:prod', NS)
            if prod is not None:
                items.append({
                    'codigo':     prod.findtext('nfe:cProd', '', NS),
                    'descricao':  prod.findtext('nfe:xProd', '', NS),
                    'ncm':        prod.findtext('nfe:NCM',   '', NS),
                    'cfop':       prod.findtext('nfe:CFOP',  '', NS),
                    'unidade':    prod.findtext('nfe:uCom',  '', NS),
                    'quantidade': float(prod.findtext('nfe:qCom',   '0', NS) or 0),
                    'vUnitario':  float(prod.findtext('nfe:vUnCom', '0', NS) or 0),
                    'vTotal':     float(prod.findtext('nfe:vProd',  '0', NS) or 0),
                })

        infNFe = root.find('.//nfe:infNFe', NS)
        chNFe  = infNFe.get('Id', '').replace('NFe', '') if infNFe is not None else ''
        nProt  = find('.//nfe:nProt')
        cStat  = find('.//nfe:cStat')

        modFrete_map = {'0':'Emitente','1':'Destinatario','2':'Terceiros','9':'Sem frete'}
        modFrete = modFrete_map.get(find('.//nfe:modFrete'), find('.//nfe:modFrete'))

        tPag_map = {'01':'Dinheiro','02':'Cheque','03':'Cartao Credito',
                    '04':'Cartao Debito','15':'Boleto','99':'Outros'}
        tPag = tPag_map.get(find('.//nfe:tPag'), find('.//nfe:tPag'))
        vPag = find('.//nfe:vPag')

        dt_emissao = None
        if dhEmi:
            try:
                dt_emissao = datetime.fromisoformat(dhEmi[:19]).strftime('%d/%m/%Y %H:%M')
            except Exception:
                dt_emissao = dhEmi

        nota = {
            'arquivo':     os.path.basename(filepath),
            'filepath':    filepath,
            'pasta':       os.path.dirname(filepath),
            'nNF':         nNF,
            'chave':       chNFe,
            'dhEmi':       dt_emissao,
            'dhEmi_raw':   dhEmi,
            'natOp':       natOp,
            'tpNF':        tpNF,
            'emit_nome':   emit_nome,
            'emit_cnpj':   emit_cnpj,
            'emit_mun':    emit_mun,
            'emit_uf':     emit_uf,
            'dest_nome':   dest_nome,
            'dest_cnpj':   dest_cnpj,
            'dest_mun':    dest_mun,
            'dest_uf':     dest_uf,
            'vNF':         float(vNF     or 0),
            'vProd':       float(vProd   or 0),
            'vICMS':       float(vICMS   or 0),
            'vST':         float(vST     or 0),
            'vPIS':        float(vPIS    or 0),
            'vCOFINS':     float(vCOFINS or 0),
            'nProt':       nProt,
            'cStat':       cStat,
            'transp_nome': find('.//nfe:transporta/nfe:xNome'),
            'modFrete':    modFrete,
            'tPag':        tPag,
            'vPag':        float(vPag or 0),
            'items':       items,
            'status':      'ok',
        }
        nota['nome_sugerido'] = gerar_nome_sugerido(nota)
        return nota

    except Exception as e:
        return {
            'arquivo':  os.path.basename(filepath),
            'filepath': filepath,
            'pasta':    os.path.dirname(filepath),
            'status':   'erro',
            'erro':     str(e),
        }

# ── rotas ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def api_upload():
    import tempfile
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'Nenhum arquivo enviado.'}), 400
    notas = []
    for f in files:
        if not f.filename.lower().endswith('.xml'):
            continue
        try:
            raw = f.read()
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xml') as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            nota = parse_nfe(tmp_path)
            nota['arquivo']       = f.filename
            nota['filepath']      = f.filename
            nota['pasta']         = ''
            nota['nome_sugerido'] = gerar_nome_sugerido(nota)
            notas.append(nota)
        except Exception as e:
            notas.append({'arquivo': f.filename, 'filepath': f.filename,
                          'pasta': '', 'status': 'erro', 'erro': str(e)})
    return jsonify({'notas': notas, 'total': len(notas)})


@app.route('/api/renomear', methods=['POST'])
def api_renomear():
    data      = get_json_body()
    filepath  = normalizar_path(data.get('filepath', ''))
    novo_nome = data.get('novo_nome', '').strip()

    if not filepath or not os.path.isfile(filepath):
        return jsonify({'error': 'Arquivo nao encontrado: ' + filepath}), 400
    if not novo_nome:
        return jsonify({'error': 'Nome nao pode ser vazio.'}), 400
    if not re.match(r'^[A-Za-z0-9_\-]+$', novo_nome):
        return jsonify({'error': 'Use apenas letras, numeros, _ e -.'}), 400

    novo_arquivo = novo_nome + '.xml'
    novo_path    = os.path.join(os.path.dirname(filepath), novo_arquivo)

    if os.path.exists(novo_path) and os.path.abspath(novo_path) != os.path.abspath(filepath):
        return jsonify({'error': 'Ja existe um arquivo com esse nome.'}), 400
    try:
        os.rename(filepath, novo_path)
        return jsonify({'ok': True, 'novo_path': novo_path, 'novo_nome': novo_arquivo})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/renomear_pasta', methods=['POST'])
def api_renomear_pasta():
    data    = get_json_body()
    pasta   = normalizar_path(data.get('pasta', ''))
    preview = data.get('preview', False)

    if not pasta:
        return jsonify({'error': 'Informe o caminho da pasta.'}), 400
    if not os.path.isdir(pasta):
        return jsonify({'error': 'Pasta nao encontrada: ' + pasta}), 400

    resultados = []
    try:
        arquivos = sorted(f for f in os.listdir(pasta) if f.lower().endswith('.xml'))
    except Exception as e:
        return jsonify({'error': 'Erro ao listar pasta: ' + str(e)}), 500

    for fname in arquivos:
        fpath = os.path.join(pasta, fname)
        try:
            nota = parse_nfe(fpath)
        except Exception as e:
            resultados.append({'original': fname, 'novo': None, 'erro': str(e), 'ok': False})
            continue

        if nota['status'] != 'ok':
            resultados.append({'original': fname, 'novo': None,
                                'erro': nota.get('erro', 'Erro ao ler'), 'ok': False})
            continue

        novo_nome = gerar_nome_sugerido(nota)
        if not novo_nome:
            resultados.append({'original': fname, 'novo': None,
                                'erro': 'Nao foi possivel gerar nome', 'ok': False})
            continue

        novo_arquivo = novo_nome + '.xml'
        novo_path    = os.path.join(pasta, novo_arquivo)

        if preview:
            resultados.append({'original': fname, 'novo': novo_arquivo, 'ok': True})
            continue

        try:
            if os.path.abspath(fpath) == os.path.abspath(novo_path):
                resultados.append({'original': fname, 'novo': novo_arquivo,
                                   'ok': True, 'sem_mudanca': True})
            elif os.path.exists(novo_path):
                resultados.append({'original': fname, 'novo': novo_arquivo,
                                   'erro': 'Ja existe', 'ok': False})
            else:
                os.rename(fpath, novo_path)
                resultados.append({'original': fname, 'novo': novo_arquivo, 'ok': True})
        except Exception as e:
            resultados.append({'original': fname, 'novo': novo_arquivo,
                               'erro': str(e), 'ok': False})

    feitos = sum(1 for r in resultados if r['ok'] and not r.get('sem_mudanca'))
    erros  = sum(1 for r in resultados if not r['ok'])
    return jsonify({'resultados': resultados, 'feitos': feitos,
                    'erros': erros, 'preview': preview})


if __name__ == '__main__':
    port = 5000
    url  = 'http://localhost:' + str(port)
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print('\n  NF-e Analyzer em ' + url)
    print('  Pressione CTRL+C para encerrar.\n')
    app.run(debug=False, port=port, host='127.0.0.1')
