# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date, datetime
import requests
from io import StringIO
import io, os
import base64
import pytz

# Tenta importar PyGithub para persistência.
try:
    from github import Github
except ImportError:
    # Classe dummy para evitar crash se PyGithub não estiver instalado
    class Github:
        def __init__(self, token): pass
        def get_repo(self, repo_name): return self
        def get_contents(self, path, ref): return type('Contents', (object,), {'sha': 'dummy_sha'})
        def update_file(self, path, msg, content, sha, branch): pass
        def create_file(self, path, msg, content, sha, branch): pass

# --- Nomes dos arquivos CSV e Configuração ---
CLIENTES_CSV = 'clientes.csv'
LANÇAMENTOS_CSV = 'lancamentos.csv'
PRODUTOS_TURBO_CSV = 'produtos_turbo.csv'
CASHBACK_PERCENTUAL = 0.03 # Taxa base Padrão (agora só para Nível Prata)
BONUS_INDICACAO_PERCENTUAL = 0.05 # 5% para o indicador
CASHBACK_INDICADO_PRIMEIRA_COMPRA = 0.08 # 8% para o indicado

# Configuração do logo para o novo layout
LOGO_DOCEBELLA_URL = "https://i.ibb.co/fYCWBKTm/Logo-Doce-Bella-Cosm-tico.png" # Link do logo

# --- Definição dos Níveis ---
NIVEIS = {
    'Prata': {
        'min_gasto': 0.00,
        'max_gasto': 200.00,
        'cashback_normal': 0.03, # 3%
        'cashback_turbo': 0.03, # Para indicação, Prata usa 3% mesmo
        'proximo_nivel': 'Ouro'
    },
    'Ouro': {
        'min_gasto': 200.01,
        'max_gasto': 1000.00,
        'cashback_normal': 0.07, # 7%
        'cashback_turbo': 0.10, # 10%
        'proximo_nivel': 'Diamante'
    },
    'Diamante': {
        'min_gasto': 1000.01,
        'max_gasto': float('inf'),
        'cashback_normal': 0.15, # 15%
        'cashback_turbo': 0.20, # 20%
        'proximo_nivel': 'Max'
    }
}


# --- Configuração de Persistência (Puxa do st.secrets) ---
try:
    TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO_FULL = st.secrets["REPO_NAME"]
    if "/" in REPO_FULL:
        REPO_OWNER, REPO_NAME = REPO_FULL.split("/")
    else:
        REPO_OWNER = st.secrets["REPO_OWNER"]
        REPO_NAME = REPO_FULL

    BRANCH = st.secrets.get("BRANCH", "main")
    PERSISTENCE_MODE = "GITHUB"
except KeyError:
    PERSISTENCE_MODE = "LOCAL"

# Define URL base se o modo for GITHUB
if PERSISTENCE_MODE == "GITHUB":
    URL_BASE_REPOS = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/"


# --- Configuração e Função do Telegram ---
try:
    TELEGRAM_BOT_ID = st.secrets["telegram"]["BOT_ID"]
    TELEGRAM_CHAT_ID = st.secrets["telegram"]["CHAT_ID"]
    TELEGRAM_THREAD_ID = st.secrets["telegram"].get("MESSAGE_THREAD_ID")
    TELEGRAM_ENABLED = True
except KeyError:
    TELEGRAM_ENABLED = False

def enviar_mensagem_telegram(mensagem: str):
    if not TELEGRAM_ENABLED: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_ID}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': mensagem, 'parse_mode': 'Markdown'}
    if TELEGRAM_THREAD_ID: payload['message_thread_id'] = TELEGRAM_THREAD_ID
    try:
        requests.post(url, data=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar para o Telegram: {e}")


# --- Funções de Persistência via GitHub API (PyGithub) ---

def load_csv_github(url: str) -> pd.DataFrame | None:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        df = pd.read_csv(StringIO(response.text), dtype=str)
        return df if not df.empty else None
    except Exception:
        return None

def salvar_dados_no_github(df: pd.DataFrame, file_path: str, commit_message: str):
    if PERSISTENCE_MODE != "GITHUB": return False
    df_temp = df.copy()
    for col in ['Data', 'Data Início', 'Data Fim']:
        if col in df_temp.columns:
            df_temp[col] = pd.to_datetime(df_temp[col], errors='coerce').apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '')
    try:
        g = Github(TOKEN)
        repo = g.get_repo(f"{REPO_OWNER}/{REPO_NAME}")
        csv_string = df_temp.to_csv(index=False, encoding="utf-8-sig")
        try:
            contents = repo.get_contents(file_path, ref=BRANCH)
            repo.update_file(contents.path, commit_message, csv_string, contents.sha, branch=BRANCH)
            st.toast(f"✅ Arquivo {file_path} atualizado no GitHub.")
        except Exception:
            repo.create_file(file_path, commit_message, csv_string, branch=BRANCH)
            st.toast(f"✅ Arquivo {file_path} criado no GitHub.")
        return True
    except Exception as e:
        st.error(f"❌ ERRO CRÍTICO ao salvar '{file_path}' no GitHub.")
        error_message = str(e)
        if hasattr(e, 'data') and 'message' in e.data: error_message = f"{e.status} - {e.data['message']}"
        st.error(f"Detalhes: {error_message}")
        print(f"--- ERRO DETALHADO GITHUB [{file_path}] ---\n{repr(e)}\n-----------------------------------------")
        return False


# --- Funções de Carregamento/Salvamento ---

def salvar_dados():
    """
    Salva os DataFrames de volta nos arquivos CSV.
    Apenas limpa o cache da função de carregamento, mantendo o session_state
    para garantir que a UI recarregue com os dados mais recentes.
    """
    if PERSISTENCE_MODE == "GITHUB":
        salvar_dados_no_github(st.session_state.clientes, CLIENTES_CSV, "AUTOSAVE: Atualizando clientes.")
        salvar_dados_no_github(st.session_state.lancamentos, LANÇAMENTOS_CSV, "AUTOSAVE: Atualizando lançamentos.")
        salvar_dados_no_github(st.session_state.produtos_turbo, PRODUTOS_TURBO_CSV, "AUTOSAVE: Atualizando produtos turbo.")
    else:
        st.session_state.clientes.to_csv(CLIENTES_CSV, index=False)
        st.session_state.lancamentos.to_csv(LANÇAMENTOS_CSV, index=False)
        st.session_state.produtos_turbo.to_csv(PRODUTOS_TURBO_CSV, index=False)
    
    # Limpa o cache para garantir que uma atualização manual (F5) puxe os dados mais recentes.
    st.cache_data.clear()

def carregar_dados_do_csv(file_path, df_columns):
    df = pd.DataFrame(columns=df_columns)
    if PERSISTENCE_MODE == "GITHUB":
        df_carregado = load_csv_github(f"{URL_BASE_REPOS}{file_path}")
        if df_carregado is not None: df = df_carregado
    elif os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, dtype=str)
        except pd.errors.EmptyDataError: pass
    for col in df_columns:
        if col not in df.columns: df[col] = ""
    if 'Cashback Disponível' in df.columns: df['Cashback Disponível'] = df['Cashback Disponível'].fillna('0.0')
    if 'Gasto Acumulado' in df.columns: df['Gasto Acumulado'] = df['Gasto Acumulado'].fillna('0.0')
    if 'Nivel Atual' in df.columns: df['Nivel Atual'] = df['Nivel Atual'].fillna('Prata')
    if 'Primeira Compra Feita' in df.columns: df['Primeira Compra Feita'] = df['Primeira Compra Feita'].fillna('False')
    if 'Venda Turbo' in df.columns: df['Venda Turbo'] = df['Venda Turbo'].fillna('Não')
    return df[df_columns]

@st.cache_data(show_spinner="Carregando dados dos arquivos...")
def carregar_dados():
    CLIENTES_COLS = ['Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível', 'Gasto Acumulado', 'Nivel Atual', 'Indicado Por', 'Primeira Compra Feita']
    df_clientes = carregar_dados_do_csv(CLIENTES_CSV, CLIENTES_COLS)
    df_clientes['Cashback Disponível'] = pd.to_numeric(df_clientes['Cashback Disponível'], errors='coerce').fillna(0.0)
    df_clientes['Gasto Acumulado'] = pd.to_numeric(df_clientes['Gasto Acumulado'], errors='coerce').fillna(0.0)
    df_clientes['Primeira Compra Feita'] = df_clientes['Primeira Compra Feita'].astype(str).str.lower().map({'true': True, 'false': False}).fillna(False).astype(bool)
    df_clientes['Nivel Atual'] = df_clientes['Nivel Atual'].fillna('Prata')

    LANÇAMENTOS_COLS = ['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback', 'Venda Turbo']
    df_lancamentos = carregar_dados_do_csv(LANÇAMENTOS_CSV, LANÇAMENTOS_COLS)
    if not df_lancamentos.empty:
        df_lancamentos['Data'] = pd.to_datetime(df_lancamentos['Data'], errors='coerce').dt.date
        df_lancamentos['Venda Turbo'] = df_lancamentos['Venda Turbo'].astype(str).replace({'True': 'Sim', 'False': 'Não', '': 'Não'}).fillna('Não')

    PRODUTOS_TURBO_COLS = ['Nome Produto', 'Data Início', 'Data Fim', 'Ativo']
    df_produtos_turbo = carregar_dados_do_csv(PRODUTOS_TURBO_CSV, PRODUTOS_TURBO_COLS)
    if not df_produtos_turbo.empty:
        df_produtos_turbo['Data Início'] = pd.to_datetime(df_produtos_turbo['Data Início'], errors='coerce').dt.date
        df_produtos_turbo['Data Fim'] = pd.to_datetime(df_produtos_turbo['Data Fim'], errors='coerce').dt.date
        df_produtos_turbo['Ativo'] = df_produtos_turbo['Ativo'].astype(str).str.lower().map({'true': True, 'false': False}).fillna(False).astype(bool)

    return df_clientes, df_lancamentos, df_produtos_turbo


# --- Funções de Lógica de Negócio (Clientes, Vendas, etc.) ---

def calcular_nivel_e_beneficios(gasto_acumulado: float):
    if gasto_acumulado >= NIVEIS['Diamante']['min_gasto']: nivel = 'Diamante'
    elif gasto_acumulado >= NIVEIS['Ouro']['min_gasto']: nivel = 'Ouro'
    else: nivel = 'Prata'
    return nivel, NIVEIS[nivel]['cashback_normal'], NIVEIS[nivel]['cashback_turbo']

def cadastrar_cliente(nome, apelido, telefone, indicado_por=''):
    if nome in st.session_state.clientes['Nome'].values:
        st.error("Erro: Já existe um cliente com este nome.")
        return
    if indicado_por and indicado_por not in st.session_state.clientes['Nome'].values:
         st.warning(f"Atenção: Cliente indicador '{indicado_por}' não encontrado.")
         indicado_por = ''
    novo_cliente = pd.DataFrame([{'Nome': nome, 'Apelido/Descrição': apelido, 'Telefone': telefone,
                                  'Cashback Disponível': 0.00, 'Gasto Acumulado': 0.00, 'Nivel Atual': 'Prata',
                                  'Indicado Por': indicado_por, 'Primeira Compra Feita': False}])
    st.session_state.clientes = pd.concat([st.session_state.clientes, novo_cliente], ignore_index=True)
    salvar_dados()
    st.success(f"Cliente '{nome}' cadastrado com sucesso!")
    st.rerun()

def excluir_cliente(nome_cliente):
    st.session_state.clientes = st.session_state.clientes[st.session_state.clientes['Nome'] != nome_cliente].reset_index(drop=True)
    st.session_state.lancamentos = st.session_state.lancamentos[st.session_state.lancamentos['Cliente'] != nome_cliente].reset_index(drop=True)
    salvar_dados()
    st.success(f"Cliente '{nome_cliente}' e seu histórico foram excluídos.")
    st.rerun()
    
# ... (As outras funções como editar_cliente, lancar_venda, etc. permanecem as mesmas) ...
# (O resto do seu código de UI, render_home, render_cadastro, etc. também permanece o mesmo)

# --- EXECUÇÃO PRINCIPAL ---
st.set_page_config(layout="wide", page_title="Doce&Bella | Gestão Cashback", page_icon="🌸")

# ... (Seu CSS aqui) ...

# Bloco de Diagnóstico
if 'PERSISTENCE_MODE' not in globals():
    PERSISTENCE_MODE = "LOCAL" # Fallback
st.info(f"Modo de Persistência: {PERSISTENCE_MODE}")

# Inicialização e carregamento de dados
if 'clientes' not in st.session_state:
    df_clientes, df_lancamentos, df_produtos_turbo = carregar_dados()
    st.session_state.clientes = df_clientes
    st.session_state.lancamentos = df_lancamentos
    st.session_state.produtos_turbo = df_produtos_turbo

# Resto da renderização da UI...
# (Onde você define as páginas e chama a função render_ da página atual)
# ...
# ==============================================================================
# ESTRUTURA E LAYOUT DO STREAMLIT
# ==============================================================================

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp { background-color: #f7f7f7; }
    div.header-container {
        padding: 0px 0 0px 0; background-color: #E91E63; color: white;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); display: flex;
        justify-content: space-between; align-items: center; width: 100%;
        position: relative; z-index: 1000;
    }
    div[data-testid^="stHorizontalBlock"] button {
        border-radius: 5px 5px 0 0; margin-right: 5px; transition: all 0.2s;
        min-width: 150px; height: 45px; font-weight: bold; color: #E91E63;
        border: 1px solid #ddd; border-bottom: none; background-color: #f2f2f2;
    }
    div[data-testid^="stHorizontalBlock"] button.active-nav-button {
        background-color: white !important; border-color: #E91E63;
        color: #E91E63 !important; box-shadow: 0 -4px 6px rgba(0, 0, 0, 0.1);
    }
    .logo-container { padding: 10px 20px; background-color: transparent; }
    div[data-testid="stMetricValue"] { color: #E91E63 !important; }
    </style>
""", unsafe_allow_html=True)

# Adicionei as definições que estavam faltando para o código ser completo
def calcular_falta_para_proximo_nivel(gasto_acumulado, nivel_atual): return 0
def editar_cliente(nome_original, nome_novo, apelido, telefone): pass
def lancar_venda(cliente_nome, valor_venda, valor_cashback, data_venda, venda_turbo_selecionada): pass
def resgatar_cashback(cliente_nome, valor_resgate, valor_venda_atual, data_resgate, saldo_disponivel): pass
def render_home(): st.header("Página Principal")
def render_lancamento(): st.header("Lançamentos")
def render_cadastro(): st.header("Cadastro")
def render_produtos_turbo(): st.header("Produtos Turbo")
def render_relatorios(): st.header("Relatórios")
def render_header(): st.header("Doce&Bella")

PAGINAS = {
    "Home": render_home,
    "Lançamento": render_lancamento,
    "Cadastro": render_cadastro,
    "Produtos Turbo": render_produtos_turbo,
    "Relatórios": render_relatorios
}

if "pagina_atual" not in st.session_state: st.session_state.pagina_atual = "Home"

render_header()
st.markdown('<div style="padding: 20px;">', unsafe_allow_html=True)
PAGINAS[st.session_state.pagina_atual]()
st.markdown('</div>', unsafe_allow_html=True)
