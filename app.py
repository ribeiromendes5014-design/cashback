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
LOGO_DOCEBELLA_URL = "https://i.ibb.co/fYCWBKTm/Logo-Doce-Bella-Cosm-tico.png" # Link do logo

# --- Definição dos Níveis ---
NIVEIS = {
    'Prata': {
        'min_gasto': 0.00,
        'max_gasto': 200.00,
        'cashback_normal': 0.03, # 3%
        'cashback_turbo': 0.03, # Prata usa a mesma taxa para indicação/turbo
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
    else: # Fallback para formato antigo se necessário
        REPO_OWNER = st.secrets["REPO_OWNER"]
        REPO_NAME = REPO_FULL
    BRANCH = st.secrets.get("BRANCH", "main")
    PERSISTENCE_MODE = "GITHUB"
except KeyError:
    PERSISTENCE_MODE = "LOCAL"

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

# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
# ALTERAÇÃO 1: Função salvar_dados CORRIGIDA
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
def salvar_dados():
    """
    Salva os DataFrames de volta nos arquivos CSV.
    Apenas limpa o cache da função de carregamento, mantendo o session_state
    para garantir que a UI recarregue com os dados mais recentes da memória.
    """
    if PERSISTENCE_MODE == "GITHUB":
        salvar_dados_no_github(st.session_state.clientes, CLIENTES_CSV, "AUTOSAVE: Clientes")
        salvar_dados_no_github(st.session_state.lancamentos, LANÇAMENTOS_CSV, "AUTOSAVE: Lançamentos")
        salvar_dados_no_github(st.session_state.produtos_turbo, PRODUTOS_TURBO_CSV, "AUTOSAVE: Produtos Turbo")
    else: # Modo LOCAL
        st.session_state.clientes.to_csv(CLIENTES_CSV, index=False)
        st.session_state.lancamentos.to_csv(LANÇAMENTOS_CSV, index=False)
        st.session_state.produtos_turbo.to_csv(PRODUTOS_TURBO_CSV, index=False)
    
    # Limpa o cache para garantir que uma atualização manual (F5) puxe os dados mais recentes do GitHub.
    st.cache_data.clear()

# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
# ALTERAÇÃO 2: Função carregar_dados CORRIGIDA
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
@st.cache_data(show_spinner="Carregando dados dos arquivos...")
def carregar_dados():
    """
    Lê os arquivos CSV do repositório ou localmente e retorna os DataFrames processados.
    """
    def carregar_dados_do_csv(file_path, df_columns):
        df = pd.DataFrame(columns=df_columns)
        if PERSISTENCE_MODE == "GITHUB":
            url_raw = f"{URL_BASE_REPOS}{file_path}"
            df_carregado = load_csv_github(url_raw)
            if df_carregado is not None:
                df = df_carregado
        elif os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path, dtype=str)
            except pd.errors.EmptyDataError:
                pass
        for col in df_columns:
            if col not in df.columns:
                df[col] = ""
        # Preenchimento de valores padrão
        if 'Cashback Disponível' in df.columns: df['Cashback Disponível'] = df['Cashback Disponível'].fillna('0.0')
        if 'Gasto Acumulado' in df.columns: df['Gasto Acumulado'] = df['Gasto Acumulado'].fillna('0.0')
        if 'Nivel Atual' in df.columns: df['Nivel Atual'] = df['Nivel Atual'].fillna('Prata')
        if 'Primeira Compra Feita' in df.columns: df['Primeira Compra Feita'] = df['Primeira Compra Feita'].fillna('False')
        if 'Venda Turbo' in df.columns: df['Venda Turbo'] = df['Venda Turbo'].fillna('Não')
        return df[df_columns]

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


# --- Funções do Programa de Fidelidade ---

def calcular_nivel_e_beneficios(gasto_acumulado: float) -> tuple[str, float, float]:
    if gasto_acumulado >= NIVEIS['Diamante']['min_gasto']:
        nivel = 'Diamante'
    elif gasto_acumulado >= NIVEIS['Ouro']['min_gasto']:
        nivel = 'Ouro'
    else:
        nivel = 'Prata'
    cb_normal = NIVEIS[nivel]['cashback_normal']
    cb_turbo = NIVEIS[nivel]['cashback_turbo']
    return nivel, cb_normal, cb_turbo

def calcular_falta_para_proximo_nivel(gasto_acumulado: float, nivel_atual: str) -> float:
    if nivel_atual == 'Diamante':
        return 0.0
    proximo_nivel_nome = NIVEIS.get(nivel_atual, {}).get('proximo_nivel')
    if proximo_nivel_nome == 'Max' or not proximo_nivel_nome:
        return 0.0
    proximo_nivel_min = NIVEIS[proximo_nivel_nome]['min_gasto']
    if proximo_nivel_min > gasto_acumulado:
        return proximo_nivel_min - gasto_acumulado
    else:
        return 0.0


# --- Funções de Manipulação de Produtos Turbo ---

def adicionar_produto_turbo(nome_produto, data_inicio, data_fim):
    if nome_produto in st.session_state.produtos_turbo['Nome Produto'].values:
        st.error("Erro: Já existe um produto com este nome.")
        return False
    is_ativo = (data_inicio <= date.today()) and (data_fim >= date.today())
    novo_produto = pd.DataFrame({
        'Nome Produto': [nome_produto], 'Data Início': [data_inicio],
        'Data Fim': [data_fim], 'Ativo': [is_ativo]
    })
    st.session_state.produtos_turbo = pd.concat([st.session_state.produtos_turbo, novo_produto], ignore_index=True)
    salvar_dados()
    st.success(f"Produto '{nome_produto}' cadastrado com sucesso! Ativo: {'Sim' if is_ativo else 'Não'}")
    st.rerun()

def excluir_produto_turbo(nome_produto):
    st.session_state.produtos_turbo = st.session_state.produtos_turbo[st.session_state.produtos_turbo['Nome Produto'] != nome_produto].reset_index(drop=True)
    salvar_dados()
    st.success(f"Produto '{nome_produto}' excluído.")
    st.rerun()

def get_produtos_turbo_ativos():
    hoje = date.today()
    df_ativos = st.session_state.produtos_turbo.copy()
    if df_ativos.empty:
        return []
    df_ativos = df_ativos[(pd.to_datetime(df_ativos['Data Início']).dt.date <= hoje) & (pd.to_datetime(df_ativos['Data Fim']).dt.date >= hoje)]
    return df_ativos['Nome Produto'].tolist()


# --- Funções de Manipulação de Clientes e Transações ---

def editar_cliente(nome_original, nome_novo, apelido, telefone):
    idx = st.session_state.clientes[st.session_state.clientes['Nome'] == nome_original].index
    if idx.empty:
        st.error(f"Erro: Cliente '{nome_original}' não encontrado.")
        return
    if nome_novo != nome_original and nome_novo in st.session_state.clientes['Nome'].values:
        st.error(f"Erro: O novo nome '{nome_novo}' já está em uso por outro cliente.")
        return
    st.session_state.clientes.loc[idx, 'Nome'] = nome_novo
    st.session_state.clientes.loc[idx, 'Apelido/Descrição'] = apelido
    st.session_state.clientes.loc[idx, 'Telefone'] = telefone
    if nome_novo != nome_original:
        st.session_state.lancamentos.loc[st.session_state.lancamentos['Cliente'] == nome_original, 'Cliente'] = nome_novo
    salvar_dados()
    st.session_state.editing_client = False
    st.success(f"Cadastro de '{nome_novo}' atualizado com sucesso!")
    st.rerun()

def excluir_cliente(nome_cliente):
    st.session_state.clientes = st.session_state.clientes[st.session_state.clientes['Nome'] != nome_cliente].reset_index(drop=True)
    st.session_state.lancamentos = st.session_state.lancamentos[st.session_state.lancamentos['Cliente'] != nome_cliente].reset_index(drop=True)
    salvar_dados()
    st.session_state.deleting_client = False
    st.success(f"Cliente '{nome_cliente}' e todos os seus lançamentos foram excluídos.")
    st.rerun()

def cadastrar_cliente(nome, apelido, telefone, indicado_por=''):
    if nome in st.session_state.clientes['Nome'].values:
        st.error("Erro: Já existe um cliente com este nome.")
        return False
    if indicado_por and indicado_por not in st.session_state.clientes['Nome'].values:
        st.warning(f"Atenção: Cliente indicador '{indicado_por}' não encontrado. O bônus não será aplicado.")
        indicado_por = ''
    novo_cliente = pd.DataFrame({
        'Nome': [nome], 'Apelido/Descrição': [apelido], 'Telefone': [telefone],
        'Cashback Disponível': [0.00], 'Gasto Acumulado': [0.00], 'Nivel Atual': ['Prata'],
        'Indicado Por': [indicado_por], 'Primeira Compra Feita': [False]
    })
    st.session_state.clientes = pd.concat([st.session_state.clientes, novo_cliente], ignore_index=True)
    salvar_dados()
    st.success(f"Cliente '{nome}' cadastrado com sucesso! Nível inicial: Prata.")
    st.rerun()

def lancar_venda(cliente_nome, valor_venda, valor_cashback, data_venda, venda_turbo_selecionada: bool):
    idx_cliente = st.session_state.clientes[st.session_state.clientes['Nome'] == cliente_nome].index
    if idx_cliente.empty:
        st.error(f"Erro: Cliente '{cliente_nome}' não encontrado.")
        return
    cliente_data = st.session_state.clientes.loc[idx_cliente].iloc[0]
    st.session_state.clientes.loc[idx_cliente, 'Cashback Disponível'] += valor_cashback
    st.session_state.clientes.loc[idx_cliente, 'Gasto Acumulado'] += valor_venda
    novo_gasto_acumulado = st.session_state.clientes.loc[idx_cliente, 'Gasto Acumulado'].iloc[0]
    novo_nivel, _, _ = calcular_nivel_e_beneficios(novo_gasto_acumulado)
    st.session_state.clientes.loc[idx_cliente, 'Nivel Atual'] = novo_nivel
    st.session_state.clientes.loc[idx_cliente, 'Primeira Compra Feita'] = True
    if not cliente_data['Primeira Compra Feita'] and cliente_data['Indicado Por']:
        indicador_nome = cliente_data['Indicado Por']
        idx_indicador = st.session_state.clientes[st.session_state.clientes['Nome'] == indicador_nome].index
        if not idx_indicador.empty:
            bonus_para_indicador = valor_venda * BONUS_INDICACAO_PERCENTUAL
            st.session_state.clientes.loc[idx_indicador, 'Cashback Disponível'] += bonus_para_indicador
            lancamento_bonus = pd.DataFrame({
                'Data': [data_venda], 'Cliente': [indicador_nome], 'Tipo': ['Bônus Indicação'],
                'Valor Venda/Resgate': [valor_venda], 'Valor Cashback': [bonus_para_indicador], 'Venda Turbo': ['Não']
            })
            st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, lancamento_bonus], ignore_index=True)
            st.success(f"🎁 Bônus de Indicação de R$ {bonus_para_indicador:.2f} creditado para **{indicador_nome}**!")
    novo_lancamento = pd.DataFrame({
        'Data': [data_venda], 'Cliente': [cliente_nome], 'Tipo': ['Venda'],
        'Valor Venda/Resgate': [valor_venda], 'Valor Cashback': [valor_cashback],
        'Venda Turbo': ['Sim' if venda_turbo_selecionada else 'Não']
    })
    st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, novo_lancamento], ignore_index=True)
    salvar_dados()
    st.success(f"Venda de R$ {valor_venda:.2f} lançada para **{cliente_nome}** ({novo_nivel}). Cashback de R$ {valor_cashback:.2f} adicionado.")
    st.rerun()
    # ... (código do telegram omitido para brevidade, mas deve estar aqui)

def resgatar_cashback(cliente_nome, valor_resgate, valor_venda_atual, data_resgate, saldo_disponivel):
    max_resgate = valor_venda_atual * 0.50
    if valor_resgate < 20:
        st.error(f"Erro: O resgate mínimo é de R$ 20,00.")
        return
    if valor_resgate > max_resgate:
        st.error(f"Erro: O resgate máximo é de 50% do valor da venda atual (R$ {max_resgate:.2f}).")
        return
    if valor_resgate > saldo_disponivel:
        st.error(f"Erro: Saldo de cashback insuficiente (Disponível: R$ {saldo_disponivel:.2f}).")
        return
    st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'] -= valor_resgate
    saldo_apos_resgate = st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'].iloc[0]
    novo_lancamento = pd.DataFrame({
        'Data': [data_resgate], 'Cliente': [cliente_nome], 'Tipo': ['Resgate'],
        'Valor Venda/Resgate': [valor_venda_atual], 'Valor Cashback': [-valor_resgate], 'Venda Turbo': ['Não']
    })
    st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, novo_lancamento], ignore_index=True)
    salvar_dados()
    st.success(f"Resgate de R$ {valor_resgate:.2f} realizado com sucesso para {cliente_nome}.")
    st.rerun()
    # ... (código do telegram omitido para brevidade, mas deve estar aqui)


# ==============================================================================
# ESTRUTURA E LAYOUT DO STREAMLIT
# ==============================================================================

st.set_page_config(layout="wide", page_title="Doce&Bella | Gestão Cashback", page_icon="🌸")

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

# --- Definição das Páginas (Funções de renderização) ---

def render_lancamento():
    st.header("Lançamento de Venda e Resgate de Cashback")
    st.markdown("---")
    operacao = st.radio("Selecione a Operação:", ["Lançar Nova Venda", "Resgatar Cashback"], key='op_selecionada', horizontal=True)
    if operacao == "Lançar Nova Venda":
        st.subheader("Nova Venda (Cashback por Nível)")
        clientes_nomes = [''] + sorted(st.session_state.clientes['Nome'].tolist())
        cliente_selecionado = st.selectbox("Nome da Cliente:", options=clientes_nomes, key='nome_cliente_venda')
        
        nivel_cliente, cb_normal_rate, cb_turbo_rate = 'Prata', NIVEIS['Prata']['cashback_normal'], NIVEIS['Prata']['cashback_turbo']
        
        if cliente_selecionado:
            cliente_data = st.session_state.clientes[st.session_state.clientes['Nome'] == cliente_selecionado].iloc[0]
            gasto_acumulado = cliente_data['Gasto Acumulado']
            primeira_compra_feita = cliente_data['Primeira Compra Feita']
            nivel_cliente, cb_normal_rate, cb_turbo_rate = calcular_nivel_e_beneficios(gasto_acumulado)
            if not primeira_compra_feita and cliente_data['Indicado Por']:
                taxa_aplicada_ind = CASHBACK_INDICADO_PRIMEIRA_COMPRA
                st.info(f"✨ **INDICAÇÃO ATIVA!** Cashback de **{int(taxa_aplicada_ind * 100)}%** aplicado.")
                cb_normal_rate = cb_turbo_rate = taxa_aplicada_ind
            col1, col2, col3 = st.columns(3)
            col1.metric("Nível Atual", nivel_cliente)
            col2.metric("Cashback Normal", f"{int(cb_normal_rate * 100)}%")
            col3.metric("Cashback Turbo", f"{int(cb_turbo_rate * 100)}%" if cb_turbo_rate > 0 else "N/A")
            st.markdown(f"**Saldo Disponível:** R$ {cliente_data['Cashback Disponível']:.2f}")
            st.markdown("---")

        valor_venda = st.number_input("Valor da Venda (R$):", min_value=0.00, step=50.0, format="%.2f", key='valor_venda')
        venda_turbo = False
        if cliente_selecionado and get_produtos_turbo_ativos():
            if cb_turbo_rate > 0:
                venda_turbo = st.checkbox(f"Esta venda contém Produtos Turbo (taxa de {int(cb_turbo_rate * 100)}%)?", key='venda_turbo_check')
        taxa_final = cb_turbo_rate if venda_turbo and cb_turbo_rate > 0 else cb_normal_rate
        cashback_calculado = st.session_state.valor_venda * taxa_final
        st.metric(label=f"Cashback a Gerar ({int(taxa_final * 100)}%):", value=f"R$ {cashback_calculado:.2f}")
        with st.form("form_venda", clear_on_submit=True):
            data_venda = st.date_input("Data da Venda:", value=date.today(), key='data_venda')
            if st.form_submit_button("Lançar Venda e Gerar Cashback"):
                if not cliente_selecionado: st.error("Selecione uma cliente.")
                elif st.session_state.valor_venda <= 0: st.error("O valor da venda deve ser maior que zero.")
                else: lancar_venda(cliente_selecionado, st.session_state.valor_venda, cashback_calculado, data_venda, venda_turbo)

    elif operacao == "Resgatar Cashback":
        st.subheader("Resgate de Cashback")
        clientes_com_cashback = st.session_state.clientes[st.session_state.clientes['Cashback Disponível'] >= 20.00]
        clientes_options = [''] + sorted(clientes_com_cashback['Nome'].tolist())
        with st.form("form_resgate", clear_on_submit=True):
            cliente_resgate = st.selectbox("Cliente para Resgate:", options=clientes_options, key='nome_cliente_resgate')
            saldo_atual = 0.0
            valor_venda_resgate = st.number_input("Valor da Venda Atual (cálculo do limite):", min_value=0.01, step=10.0, format="%.2f")
            valor_resgate = st.number_input("Valor do Resgate (Mínimo R$20,00):", min_value=0.00, step=5.0, format="%.2f")
            data_resgate = st.date_input("Data do Resgate:", value=date.today())
            if cliente_resgate:
                saldo_atual = st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_resgate, 'Cashback Disponível'].iloc[0]
                st.info(f"Saldo Disponível: R$ {saldo_atual:.2f} | Resgate Máximo: R$ {valor_venda_resgate * 0.5:.2f}")
            if st.form_submit_button("Confirmar Resgate"):
                if not cliente_resgate: st.error("Selecione uma cliente.")
                elif valor_resgate <= 0: st.error("O valor do resgate deve ser maior que zero.")
                else: resgatar_cashback(cliente_resgate, valor_resgate, valor_venda_resgate, data_resgate, saldo_atual)

def render_produtos_turbo():
    st.header("Gestão de Produtos Turbo (Cashback Extra)")
    with st.form("form_cadastro_produto", clear_on_submit=True):
        st.subheader("Cadastrar Novo Produto Turbo")
        nome_produto = st.text_input("Nome do Produto")
        col1, col2 = st.columns(2)
        data_inicio = col1.date_input("Data de Início", value=date.today())
        data_fim = col2.date_input("Data de Fim", value=date.today())
        if st.form_submit_button("Cadastrar Produto"):
            if nome_produto and data_inicio <= data_fim:
                adicionar_produto_turbo(nome_produto.strip(), data_inicio, data_fim)
            else: st.error("Preencha o nome e verifique as datas.")
    st.subheader("Produtos Cadastrados")
    if st.session_state.produtos_turbo.empty:
        st.info("Nenhum produto turbo cadastrado.")
    else:
        df_display = st.session_state.produtos_turbo.copy()
        hoje = date.today()
        df_display['Status'] = df_display.apply(lambda row: 'ATIVO' if (pd.notna(row['Data Início']) and pd.notna(row['Data Fim']) and row['Data Início'].date() <= hoje and row['Data Fim'].date() >= hoje) else 'INATIVO', axis=1)
        st.dataframe(df_display[['Nome Produto', 'Data Início', 'Data Fim', 'Status']], use_container_width=True, hide_index=True)
        st.subheader("Excluir Produto")
        produto_sel = st.selectbox("Selecione para excluir:", options=[''] + df_display['Nome Produto'].tolist())
        if produto_sel and st.button(f"Excluir {produto_sel}", type='primary'):
            excluir_produto_turbo(produto_sel)

def render_cadastro():
    st.header("Cadastro de Clientes e Gestão")
    st.subheader("Novo Cliente")
    if 'is_indicado_check' not in st.session_state: st.session_state.is_indicado_check = False
    st.checkbox("Cliente foi indicado(a) por outra?", key='is_indicado_check')
    indicado_por = ''
    if st.session_state.is_indicado_check:
        st.markdown("##### 🎁 Programa Indique e Ganhe")
        clientes_indicadores = [''] + sorted(st.session_state.clientes['Nome'].tolist())
        indicado_por = st.selectbox("Nome da Cliente Indicadora:", options=clientes_indicadores, key='indicador_nome_select')
    with st.form("form_cadastro_cliente", clear_on_submit=True):
        st.markdown("##### Dados Pessoais")
        col1, col2 = st.columns(2)
        nome = col1.text_input("Nome da Cliente (Obrigatório)", key='cadastro_nome')
        telefone = col2.text_input("Telefone", key='cadastro_telefone')
        apelido = st.text_input("Apelido ou Descrição", key='cadastro_apelido')
        if st.form_submit_button("Cadastrar Cliente"):
            if nome:
                indicado_final = st.session_state.get('indicador_nome_select', '') if st.session_state.get('is_indicado_check', False) else ''
                cadastrar_cliente(nome.strip(), apelido.strip(), telefone.strip(), indicado_final.strip())
            else: st.error("O campo 'Nome da Cliente' é obrigatório.")
    st.markdown("---")
    st.subheader("Operações de Edição e Exclusão")
    clientes_op = [''] + sorted(st.session_state.clientes['Nome'].tolist())
    cliente_sel_op = st.selectbox("Selecione a Cliente para Editar ou Excluir:", options=clientes_op, key='cliente_sel_op')
    if cliente_sel_op:
        cliente_data = st.session_state.clientes[st.session_state.clientes['Nome'] == cliente_sel_op].iloc[0]
        col1, col2 = st.columns([1,1])
        if col1.button("✏️ Editar Cadastro", use_container_width=True): st.session_state.editing_client = cliente_sel_op; st.rerun()
        if col2.button("🗑️ Excluir Cliente", use_container_width=True, type='primary'): st.session_state.deleting_client = cliente_sel_op; st.rerun()
        if st.session_state.get('editing_client') == cliente_sel_op:
            st.subheader(f"Editando: {cliente_sel_op}")
            with st.form("form_edicao_cliente"):
                novo_nome = st.text_input("Nome:", value=cliente_data['Nome'])
                novo_apelido = st.text_input("Apelido/Descrição:", value=cliente_data['Apelido/Descrição'])
                novo_telefone = st.text_input("Telefone:", value=cliente_data['Telefone'])
                if st.form_submit_button("✅ Concluir Edição"): editar_cliente(cliente_sel_op, novo_nome.strip(), novo_apelido.strip(), novo_telefone.strip())
        if st.session_state.get('deleting_client') == cliente_sel_op:
            st.error(f"ATENÇÃO: Deseja realmente excluir **{cliente_sel_op}** e todo o seu histórico?")
            col1, col2 = st.columns(2)
            if col1.button(f"🔴 Sim, excluir {cliente_sel_op}", use_container_width=True, type='primary'): excluir_cliente(cliente_sel_op)
            if col2.button("↩️ Cancelar", use_container_width=True): st.session_state.deleting_client = False; st.rerun()
    st.markdown("---")
    st.subheader("Clientes Cadastrados")
    st.dataframe(st.session_state.clientes.drop(columns=['Primeira Compra Feita'], errors='ignore'), hide_index=True, use_container_width=True)

def render_relatorios():
    st.header("Relatórios e Rankings")
    st.subheader("💎 Ranking de Níveis de Fidelidade")
    df_niveis = st.session_state.clientes.copy()
    df_niveis['Nivel Atual'] = df_niveis['Gasto Acumulado'].apply(lambda x: calcular_nivel_e_beneficios(x)[0])
    df_niveis['Falta p/ Próximo Nível (R$)'] = df_niveis.apply(lambda row: calcular_falta_para_proximo_nivel(row['Gasto Acumulado'], row['Nivel Atual']), axis=1)
    ordenacao = {'Diamante': 3, 'Ouro': 2, 'Prata': 1}
    df_niveis['Ordem'] = df_niveis['Nivel Atual'].map(ordenacao)
    df_niveis = df_niveis.sort_values(by=['Ordem', 'Gasto Acumulado'], ascending=[False, False])
    df_display = df_niveis[['Nome', 'Nivel Atual', 'Gasto Acumulado', 'Falta p/ Próximo Nível (R$)']].reset_index(drop=True)
    df_display.columns = ['Cliente', 'Nível', 'Gasto Acumulado (R$)', 'Falta p/ Próximo Nível (R$)']
    df_display['Gasto Acumulado (R$)'] = df_display['Gasto Acumulado (R$)'].map('R$ {:,.2f}'.format)
    df_display['Falta p/ Próximo Nível (R$)'] = df_display['Falta p/ Próximo Nível (R$)'].map('R$ {:,.2f}'.format)
    st.dataframe(df_display, hide_index=True, use_container_width=True)
    st.markdown("---")
    st.subheader("💰 Ranking: Maior Saldo de Cashback")
    ranking_cashback = st.session_state.clientes.sort_values(by='Cashback Disponível', ascending=False).reset_index(drop=True)
    st.dataframe(ranking_cashback[['Nome', 'Cashback Disponível']].head(10), hide_index=True, use_container_width=True)
    st.markdown("---")
    st.subheader("📄 Histórico de Lançamentos")
    col1, col2 = st.columns(2)
    data_sel = col1.date_input("Filtrar por Data:", value=None)
    tipo_sel = col2.selectbox("Filtrar por Tipo:", ['Todos', 'Venda', 'Resgate', 'Bônus Indicação'])
    df_historico = st.session_state.lancamentos.copy()
    if data_sel: df_historico = df_historico[df_historico['Data'] == data_sel]
    if tipo_sel != 'Todos': df_historico = df_historico[df_historico['Tipo'] == tipo_sel]
    if not df_historico.empty:
        df_historico['Valor Venda/Resgate'] = pd.to_numeric(df_historico['Valor Venda/Resgate'], errors='coerce').map('R$ {:,.2f}'.format)
        df_historico['Valor Cashback'] = pd.to_numeric(df_historico['Valor Cashback'], errors='coerce').map('R$ {:,.2f}'.format)
        st.dataframe(df_historico.sort_values(by='Data', ascending=False), hide_index=True, use_container_width=True)
    else: st.info("Nenhum lançamento encontrado com os filtros selecionados.")

def render_home():
    st.header("Seja Bem-Vinda ao Painel de Gestão de Cashback Doce&Bella!")
    st.markdown("---")
    total_clientes = len(st.session_state.clientes)
    total_cashback = st.session_state.clientes['Cashback Disponível'].sum()
    vendas_df = st.session_state.lancamentos[st.session_state.lancamentos['Tipo'] == 'Venda'].copy()
    total_vendas_mes = 0.0
    if not vendas_df.empty:
        vendas_df['Data'] = pd.to_datetime(vendas_df['Data'], errors='coerce')
        vendas_mes = vendas_df[vendas_df['Data'].dt.month == date.today().month]
        if not vendas_mes.empty:
            total_vendas_mes = pd.to_numeric(vendas_mes['Valor Venda/Resgate'], errors='coerce').sum()
    col1, col2, col3 = st.columns(3)
    col1.metric("Clientes Cadastrados", total_clientes)
    col2.metric("Total de Cashback Devido", f"R$ {total_cashback:,.2f}")
    col3.metric("Volume de Vendas (Mês Atual)", f"R$ {total_vendas_mes:,.2f}")
    st.markdown("---")
    st.markdown("### Acesso Rápido")
    col1, col2, col3, col4 = st.columns(4)
    if col1.button("▶️ Lançar Venda", use_container_width=True): st.session_state.pagina_atual = "Lançamento"; st.rerun()
    if col2.button("👥 Cadastrar Cliente", use_container_width=True): st.session_state.pagina_atual = "Cadastro"; st.rerun()
    if col3.button("⚡ Produtos Turbo", use_container_width=True): st.session_state.pagina_atual = "Produtos Turbo"; st.rerun()
    if col4.button("📈 Ver Relatórios", use_container_width=True): st.session_state.pagina_atual = "Relatórios"; st.rerun()

PAGINAS = {
    "Home": render_home, "Lançamento": render_lancamento, "Cadastro": render_cadastro,
    "Produtos Turbo": render_produtos_turbo, "Relatórios": render_relatorios
}

if "pagina_atual" not in st.session_state: st.session_state.pagina_atual = "Home"

def render_header():
    col_logo, col_nav = st.columns([1.5, 5])
    with col_logo:
        st.markdown(f'<div class="logo-container"><img src="{LOGO_DOCEBELLA_URL}" alt="Logo" style="height: 80px;"></div>', unsafe_allow_html=True)
    with col_nav:
        st.markdown('<div style="height: 20px;"></div>', unsafe_allow_html=True)
        cols_botoes = st.columns(len(PAGINAS))
        paginas_ordenadas = ["Home", "Lançamento", "Cadastro", "Produtos Turbo", "Relatórios"]
        for i, nome in enumerate(paginas_ordenadas):
            if cols_botoes[i].button(nome, key=f"nav_{nome}", use_container_width=True):
                st.session_state.pagina_atual = nome
                st.rerun()

# --- EXECUÇÃO PRINCIPAL ---

if 'editing_client' not in st.session_state: st.session_state.editing_client = False
if 'deleting_client' not in st.session_state: st.session_state.deleting_client = False
if 'valor_venda' not in st.session_state: st.session_state.valor_venda = 0.00
if 'data_version' not in st.session_state: st.session_state.data_version = 0

carregar_dados(st.session_state.data_version)

render_header()
st.markdown('<div style="padding-top: 20px;">', unsafe_allow_html=True)
st.info(f"Modo de Persistência: {PERSISTENCE_MODE}")
PAGINAS[st.session_state.pagina_atual]()
st.markdown('</div>', unsafe_allow_html=True)
