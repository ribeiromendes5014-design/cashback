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
BONUS_INDICACAO_PERCENTUAL = 0.05 # 5% para o indicador
CASHBACK_INDICADO_PRIMEIRA_COMPRA = 0.08 # 8% para o indicado

# Configuração do logo para o novo layout
LOGO_DOCEBELLA_URL = "https://i.ibb.co/fYCWBKTm/Logo-Doce-Bella-Cosm-tico.png"

# --- Definição dos Níveis ---
NIVEIS = {
    'Prata': {
        'min_gasto': 0.00, 'max_gasto': 200.00, 'cashback_normal': 0.03,
        'cashback_turbo': 0.03, 'proximo_nivel': 'Ouro'
    },
    'Ouro': {
        'min_gasto': 200.01, 'max_gasto': 1000.00, 'cashback_normal': 0.07,
        'cashback_turbo': 0.10, 'proximo_nivel': 'Diamante'
    },
    'Diamante': {
        'min_gasto': 1000.01, 'max_gasto': float('inf'), 'cashback_normal': 0.15,
        'cashback_turbo': 0.20, 'proximo_nivel': 'Max'
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

if PERSISTENCE_MODE == "GITHUB":
    URL_BASE_REPOS = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/"

# --- Funções de Persistência e Utilitários ---

def load_csv_github(url: str):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return pd.read_csv(StringIO(response.text), dtype=str)
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

def salvar_dados():
    if PERSISTENCE_MODE == "GITHUB":
        salvar_dados_no_github(st.session_state.clientes, CLIENTES_CSV, "AUTOSAVE: Clientes")
        salvar_dados_no_github(st.session_state.lancamentos, LANÇAMENTOS_CSV, "AUTOSAVE: Lançamentos")
        salvar_dados_no_github(st.session_state.produtos_turbo, PRODUTOS_TURBO_CSV, "AUTOSAVE: Produtos Turbo")
    else:
        st.session_state.clientes.to_csv(CLIENTES_CSV, index=False)
        st.session_state.lancamentos.to_csv(LANÇAMENTOS_CSV, index=False)
        st.session_state.produtos_turbo.to_csv(PRODUTOS_TURBO_CSV, index=False)
    st.cache_data.clear()

@st.cache_data(show_spinner="Carregando dados dos arquivos...")
def carregar_dados():
    def carregar_csv(file_path, columns):
        df = pd.DataFrame(columns=columns)
        if PERSISTENCE_MODE == "GITHUB":
            df_carregado = load_csv_github(f"{URL_BASE_REPOS}{file_path}")
            if df_carregado is not None: df = df_carregado
        elif os.path.exists(file_path):
            try: df = pd.read_csv(file_path, dtype=str)
            except pd.errors.EmptyDataError: pass
        for col in columns:
            if col not in df.columns: df[col] = ""
        return df

    CLIENTES_COLS = ['Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível', 'Gasto Acumulado', 'Nivel Atual', 'Indicado Por', 'Primeira Compra Feita']
    df_clientes = carregar_csv(CLIENTES_CSV, CLIENTES_COLS)
    df_clientes['Cashback Disponível'] = pd.to_numeric(df_clientes['Cashback Disponível'], errors='coerce').fillna(0.0)
    df_clientes['Gasto Acumulado'] = pd.to_numeric(df_clientes['Gasto Acumulado'], errors='coerce').fillna(0.0)
    df_clientes['Primeira Compra Feita'] = df_clientes['Primeira Compra Feita'].astype(str).str.lower().map({'true': True, 'false': False}).fillna(False).astype(bool)
    
    LANÇAMENTOS_COLS = ['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback', 'Venda Turbo']
    df_lancamentos = carregar_csv(LANÇAMENTOS_CSV, LANÇAMENTOS_COLS)
    df_lancamentos['Data'] = pd.to_datetime(df_lancamentos['Data'], errors='coerce').dt.date

    PRODUTOS_TURBO_COLS = ['Nome Produto', 'Data Início', 'Data Fim', 'Ativo']
    df_produtos_turbo = carregar_csv(PRODUTOS_TURBO_CSV, PRODUTOS_TURBO_COLS)
    df_produtos_turbo['Data Início'] = pd.to_datetime(df_produtos_turbo['Data Início'], errors='coerce').dt.date
    df_produtos_turbo['Data Fim'] = pd.to_datetime(df_produtos_turbo['Data Fim'], errors='coerce').dt.date
    df_produtos_turbo['Ativo'] = df_produtos_turbo['Ativo'].astype(str).str.lower().map({'true': True, 'false': False}).fillna(False).astype(bool)

    return df_clientes, df_lancamentos, df_produtos_turbo

def calcular_nivel_e_beneficios(gasto_acumulado: float):
    if gasto_acumulado >= NIVEIS['Diamante']['min_gasto']: nivel = 'Diamante'
    elif gasto_acumulado >= NIVEIS['Ouro']['min_gasto']: nivel = 'Ouro'
    else: nivel = 'Prata'
    return nivel, NIVEIS[nivel]['cashback_normal'], NIVEIS[nivel]['cashback_turbo']

# --- Funções das Páginas (Renderização da UI) ---

def render_home():
    st.header("Painel de Gestão de Cashback Doce&Bella")
    total_clientes = len(st.session_state.clientes)
    total_cashback = st.session_state.clientes['Cashback Disponível'].sum()
    col1, col2 = st.columns(2)
    col1.metric("Clientes Cadastrados", total_clientes)
    col2.metric("Total de Cashback Devido", f"R$ {total_cashback:,.2f}")

def render_cadastro():
    st.header("Cadastro e Gestão de Clientes")
    with st.expander("➕ Cadastrar Nova Cliente", expanded=True):
        with st.form("form_cadastro_cliente", clear_on_submit=True):
            nome = st.text_input("Nome da Cliente (Obrigatório)")
            if st.form_submit_button("Cadastrar Cliente"):
                if nome:
                    if nome not in st.session_state.clientes['Nome'].values:
                        novo_cliente = pd.DataFrame([{'Nome': nome, 'Cashback Disponível': 0.0, 'Gasto Acumulado': 0.0}])
                        st.session_state.clientes = pd.concat([st.session_state.clientes, novo_cliente], ignore_index=True)
                        salvar_dados()
                        st.success(f"Cliente '{nome}' cadastrada!")
                        st.rerun()
                    else:
                        st.error("Já existe uma cliente com este nome.")
                else:
                    st.error("O nome é obrigatório.")
    st.subheader("Clientes Cadastrados")
    st.dataframe(st.session_state.clientes, use_container_width=True)

# Adicione aqui as outras funções de renderização completas (render_lancamento, etc.)
# ...

# --- Execução Principal ---
st.set_page_config(layout="wide", page_title="Doce&Bella Cashback", page_icon="🌸")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;}</style>", unsafe_allow_html=True)

if 'clientes' not in st.session_state:
    st.session_state.clientes, st.session_state.lancamentos, st.session_state.produtos_turbo = carregar_dados()

if 'pagina_atual' not in st.session_state:
    st.session_state.pagina_atual = "Home"

st.sidebar.title("Navegação")
pagina_selecionada = st.sidebar.radio("Escolha uma página", ["Home", "Cadastro", "Lançamento", "Produtos Turbo", "Relatórios"])

if pagina_selecionada == "Home":
    render_home()
elif pagina_selecionada == "Cadastro":
    render_cadastro()
# Adicione as chamadas para as outras páginas aqui

st.info(f"Modo de Persistência: {PERSISTENCE_MODE}")
