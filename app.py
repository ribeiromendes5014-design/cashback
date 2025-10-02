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
LOGO_DOCEBELLA_URL = "https://i.ibb.co/wYkWmGk/Logo-Doce-Bella-Cosm-tico.png" # Link do logo

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
        # Fallback para o formato antigo, se necessário
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
    """Envia uma mensagem para o Telegram usando a API do bot."""
    if not TELEGRAM_ENABLED:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_ID}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': mensagem,
        'parse_mode': 'Markdown'
    }
    if TELEGRAM_THREAD_ID:
        payload['message_thread_id'] = TELEGRAM_THREAD_ID

    try:
        requests.post(url, data=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar para o Telegram: {e}")
        pass


# --- Funções de Persistência via GitHub API (PyGithub) ---

def load_csv_github(url: str) -> pd.DataFrame | None:
    """Carrega um CSV do GitHub usando a URL raw."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        df = pd.read_csv(StringIO(response.text), dtype=str)
        if df.empty or len(df.columns) < 2:
            return None
        return df
    except Exception:
        return None

def salvar_dados_no_github(df: pd.DataFrame, file_path: str, commit_message: str):
    """Salva o DataFrame CSV no GitHub usando a API (PyGithub)."""
    if PERSISTENCE_MODE != "GITHUB":
        return False

    df_temp = df.copy()
    date_columns = ['Data', 'Data Início', 'Data Fim']
    for col in date_columns:
        if col in df_temp.columns:
             df_temp[col] = pd.to_datetime(df_temp[col], errors='coerce').apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '')

    try:
        g = Github(TOKEN)
        repo = g.get_repo(f"{REPO_OWNER}/{REPO_NAME}")
        csv_string = df_temp.to_csv(index=False, encoding="utf-8-sig")

        try:
            contents = repo.get_contents(file_path, ref=BRANCH)
            repo.update_file(contents.path, commit_message, csv_string, contents.sha, branch=BRANCH)
            st.toast(f"✅ Arquivo {file_path} salvo no GitHub.")
        except Exception:
            repo.create_file(file_path, commit_message, csv_string, branch=BRANCH)
            st.toast(f"✅ Arquivo {file_path} criado no GitHub.")
        return True
    except Exception as e:
        st.error(f"❌ ERRO CRÍTICO ao salvar no GitHub ({file_path}): {e}")
        return False


# --- Funções de Carregamento/Salvamento ---

def salvar_dados():
    """
    Salva os DataFrames de volta nos arquivos CSV, priorizando o GitHub.
    Limpa o cache e o session_state para forçar a releitura dos dados do CSV.
    """
    if PERSISTENCE_MODE == "GITHUB":
        salvar_dados_no_github(st.session_state.clientes, CLIENTES_CSV, "AUTOSAVE: Atualizando clientes.")
        salvar_dados_no_github(st.session_state.lancamentos, LANÇAMENTOS_CSV, "AUTOSAVE: Atualizando lançamentos.")
        salvar_dados_no_github(st.session_state.produtos_turbo, PRODUTOS_TURBO_CSV, "AUTOSAVE: Atualizando produtos turbo.")
    else: # Modo LOCAL
        st.session_state.clientes.to_csv(CLIENTES_CSV, index=False)
        st.session_state.lancamentos.to_csv(LANÇAMENTOS_CSV, index=False)
        st.session_state.produtos_turbo.to_csv(PRODUTOS_TURBO_CSV, index=False)

    # >>>>> MUDANÇA CRÍTICA <<<<<
    # Limpa o cache para a função carregar_dados
    st.cache_data.clear()

    # Remove os dataframes do estado da sessão para forçar a recarga a partir do CSV
    if 'clientes' in st.session_state:
        del st.session_state.clientes
    if 'lancamentos' in st.session_state:
        del st.session_state.lancamentos
    if 'produtos_turbo' in st.session_state:
        del st.session_state.produtos_turbo


def carregar_dados_do_csv(file_path, df_columns):
    """Lógica para carregar CSV local ou do GitHub, garantindo as colunas."""
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

    # Preenche valores NaN/vazios com padrões
    if 'Cashback Disponível' in df.columns: df['Cashback Disponível'] = df['Cashback Disponível'].fillna('0.0')
    if 'Gasto Acumulado' in df.columns: df['Gasto Acumulado'] = df['Gasto Acumulado'].fillna('0.0')
    if 'Nivel Atual' in df.columns: df['Nivel Atual'] = df['Nivel Atual'].fillna('Prata')
    if 'Primeira Compra Feita' in df.columns: df['Primeira Compra Feita'] = df['Primeira Compra Feita'].fillna('False')
    if 'Venda Turbo' in df.columns: df['Venda Turbo'] = df['Venda Turbo'].fillna('Não')

    return df[df_columns]

@st.cache_data(show_spinner="Carregando dados dos arquivos...")
def carregar_dados(): # <<<<< MUDANÇA: Não precisa mais de argumento
    """
    Lê os arquivos CSV e retorna os DataFrames processados.
    Esta função não deve modificar st.session_state diretamente.
    """
    # 1. CLIENTES
    CLIENTES_COLS = ['Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível', 'Gasto Acumulado', 'Nivel Atual', 'Indicado Por', 'Primeira Compra Feita']
    df_clientes = carregar_dados_do_csv(CLIENTES_CSV, CLIENTES_COLS)
    df_clientes['Cashback Disponível'] = pd.to_numeric(df_clientes['Cashback Disponível'], errors='coerce').fillna(0.0)
    df_clientes['Gasto Acumulado'] = pd.to_numeric(df_clientes['Gasto Acumulado'], errors='coerce').fillna(0.0)
    df_clientes['Primeira Compra Feita'] = df_clientes['Primeira Compra Feita'].astype(str).str.lower().map({'true': True, 'false': False}).fillna(False).astype(bool)
    df_clientes['Nivel Atual'] = df_clientes['Nivel Atual'].fillna('Prata')

    # 2. LANÇAMENTOS
    LANÇAMENTOS_COLS = ['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback', 'Venda Turbo']
    df_lancamentos = carregar_dados_do_csv(LANÇAMENTOS_CSV, LANÇAMENTOS_COLS)
    if not df_lancamentos.empty:
        df_lancamentos['Data'] = pd.to_datetime(df_lancamentos['Data'], errors='coerce').dt.date
        df_lancamentos['Venda Turbo'] = df_lancamentos['Venda Turbo'].astype(str).replace({'True': 'Sim', 'False': 'Não', '': 'Não'}).fillna('Não')

    # 3. PRODUTOS TURBO
    PRODUTOS_TURBO_COLS = ['Nome Produto', 'Data Início', 'Data Fim', 'Ativo']
    df_produtos_turbo = carregar_dados_do_csv(PRODUTOS_TURBO_CSV, PRODUTOS_TURBO_COLS)
    if not df_produtos_turbo.empty:
        df_produtos_turbo['Data Início'] = pd.to_datetime(df_produtos_turbo['Data Início'], errors='coerce').dt.date
        df_produtos_turbo['Data Fim'] = pd.to_datetime(df_produtos_turbo['Data Fim'], errors='coerce').dt.date
        df_produtos_turbo['Ativo'] = df_produtos_turbo['Ativo'].astype(str).str.lower().map({'true': True, 'false': False}).fillna(False).astype(bool)

    # <<<<< MUDANÇA CRÍTICA: A função agora retorna os dataframes
    return df_clientes, df_lancamentos, df_produtos_turbo


# --- AS DEMAIS FUNÇÕES (calcular_nivel, excluir_cliente, etc.) FICAM EXATAMENTE IGUAIS ---
# ... (todo o resto do seu código até a seção de execução principal)
# ...
# COLE AQUI TODAS AS SUAS FUNÇÕES, DESDE "Funções do Programa de Fidelidade"
# ATÉ ANTES DE "EXECUÇÃO PRINCIPAL"
# ...
# --- Funções do Programa de Fidelidade ---

def calcular_nivel_e_beneficios(gasto_acumulado: float) -> tuple[str, float, float]:
    """Calcula o nível, cashback normal e turbo com base no gasto acumulado."""
    
    # Inicializa com o nível base
    nivel = 'Prata'
    cb_normal = NIVEIS['Prata']['cashback_normal']
    cb_turbo = NIVEIS['Prata']['cashback_turbo']
    
    # CORREÇÃO: A lógica de nível usa > ou >= nos limites mínimos (min_gasto)
    if gasto_acumulado >= NIVEIS['Diamante']['min_gasto']:
        nivel = 'Diamante'
        cb_normal = NIVEIS['Diamante']['cashback_normal']
        cb_turbo = NIVEIS['Diamante']['cashback_turbo']
    # Ouro começa a partir de R$ 200.01 (min_gasto)
    elif gasto_acumulado >= NIVEIS['Ouro']['min_gasto']:
        nivel = 'Ouro'
        cb_normal = NIVEIS['Ouro']['cashback_normal']
        cb_turbo = NIVEIS['Ouro']['cashback_turbo']
    # Se não atingiu R$ 200.01, permanece Prata
    
    return nivel, cb_normal, cb_turbo

def calcular_falta_para_proximo_nivel(gasto_acumulado: float, nivel_atual: str) -> float:
    """Calcula quanto falta para o próximo nível."""
    if nivel_atual == 'Diamante':
        return 0.0 # Nível máximo
        
    # Obtém o nome do próximo nível
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
    """Adiciona um novo produto turbo ao DataFrame."""
    if nome_produto in st.session_state.produtos_turbo['Nome Produto'].values:
        st.error("Erro: Já existe um produto com este nome.")
        return False
    
    # Define se está ativo na hora do cadastro
    is_ativo = (data_inicio <= date.today()) and (data_fim >= date.today())
        
    novo_produto = pd.DataFrame({
        'Nome Produto': [nome_produto],
        'Data Início': [data_inicio],
        'Data Fim': [data_fim],
        'Ativo': [is_ativo]
    })
    st.session_state.produtos_turbo = pd.concat([st.session_state.produtos_turbo, novo_produto], ignore_index=True)
    salvar_dados()  
    st.success(f"Produto '{nome_produto}' cadastrado com sucesso! Ativo: {'Sim' if is_ativo else 'Não'}")
    st.rerun()

def excluir_produto_turbo(nome_produto):
    """Exclui um produto turbo."""
    st.session_state.produtos_turbo = st.session_state.produtos_turbo[
        st.session_state.produtos_turbo['Nome Produto'] != nome_produto
    ].reset_index(drop=True)
    salvar_dados()
    st.success(f"Produto '{nome_produto}' excluído.")
    st.rerun()

def get_produtos_turbo_ativos():
    """Retorna uma lista dos nomes dos produtos turbo ativos na data de hoje."""
    hoje = date.today()
    
    df_ativos = st.session_state.produtos_turbo.copy()

    # Filtra produtos que estão ativos no período
    df_ativos = df_ativos[
        (df_ativos['Data Início'] <= hoje) & 
        (df_ativos['Data Fim'] >= hoje)
    ]
    return df_ativos['Nome Produto'].tolist()


# --- Funções de Manipulação de Clientes e Transações ---

def editar_cliente(nome_original, nome_novo, apelido, telefone):
    """Localiza o cliente pelo nome original, atualiza os dados e salva."""
    
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
    """Exclui o cliente e todas as suas transações, salva no CSV e força recarregamento."""
    
    # Remove do DataFrame de clientes
    st.session_state.clientes = st.session_state.clientes[
        st.session_state.clientes['Nome'] != nome_cliente
    ].reset_index(drop=True)
    
    # Remove do DataFrame de lançamentos
    st.session_state.lancamentos = st.session_state.lancamentos[
        st.session_state.lancamentos['Cliente'] != nome_cliente
    ].reset_index(drop=True)
    
    salvar_dados()
    
    st.session_state.deleting_client = False
    st.success(f"Cliente '{nome_cliente}' e todos os seus lançamentos foram excluídos.")
    st.rerun()


def cadastrar_cliente(nome, apelido, telefone, indicado_por=''):
    """Adiciona um novo cliente ao DataFrame de clientes e salva o CSV."""
    
    if nome in st.session_state.clientes['Nome'].values:
        st.error("Erro: Já existe um cliente com este nome.")
        return False
    
    # Validação do Indicador
    if indicado_por and indicado_por not in st.session_state.clientes['Nome'].values:
         st.warning(f"Atenção: Cliente indicador '{indicado_por}' não encontrado. O bônus não será aplicado.")
         indicado_por = '' # Zera o campo se o indicador não existir
        
    novo_cliente = pd.DataFrame({
        'Nome': [nome],
        'Apelido/Descrição': [apelido],
        'Telefone': [telefone],
        'Cashback Disponível': [0.00],
        'Gasto Acumulado': [0.00],
        'Nivel Atual': ['Prata'],
        'Indicado Por': [indicado_por],
        'Primeira Compra Feita': [False]
    })
    st.session_state.clientes = pd.concat([st.session_state.clientes, novo_cliente], ignore_index=True)
    salvar_dados()  
    st.success(f"Cliente '{nome}' cadastrado com sucesso! Nível inicial: Prata.")
    st.rerun()

def lancar_venda(cliente_nome, valor_venda, valor_cashback, data_venda, venda_turbo_selecionada: bool):
    """Lança uma venda, atualiza o cashback do cliente e do indicador, salva e envia notificação."""
    
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
    
    bonus_para_indicador = 0.0
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

    # Telegram logic...
    # ...

def resgatar_cashback(cliente_nome, valor_resgate, valor_venda_atual, data_resgate, saldo_disponivel):
    """Processa o resgate de cashback."""
    max_resgate = valor_venda_atual * 0.50
    if valor_resgate < 20:
        st.error("Erro: O resgate mínimo é de R$ 20,00.")
        return
    if valor_resgate > max_resgate:
        st.error(f"Erro: O resgate máximo é de 50% do valor da venda atual (R$ {max_resgate:.2f}).")
        return
    if valor_resgate > saldo_disponivel:
        st.error(f"Erro: Saldo de cashback insuficiente (Disponível: R$ {saldo_disponivel:.2f}).")
        return
        
    st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'] -= valor_resgate
    
    novo_lancamento = pd.DataFrame({
        'Data': [data_resgate], 'Cliente': [cliente_nome], 'Tipo': ['Resgate'],
        'Valor Venda/Resgate': [valor_venda_atual], 'Valor Cashback': [-valor_resgate], 'Venda Turbo': ['Não']
    })
    st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, novo_lancamento], ignore_index=True)
    
    salvar_dados()  
    st.success(f"Resgate de R$ {valor_resgate:.2f} realizado com sucesso para {cliente_nome}.")
    st.rerun()
    # Telegram logic...
    # ...


# ==============================================================================
# ESTRUTURA E LAYOUT DO STREAMLIT (NÃO PRECISA MUDAR NADA AQUI)
# ... Cole aqui toda a sua seção de layout, de st.set_page_config até o final
# das funções render_...
# ==============================================================================

# Configuração da página
st.set_page_config(
    layout="wide",  
    page_title="Doce&Bella | Gestão Cashback",  
    page_icon="🌸"
)

# Adiciona CSS para o layout customizado (Doce&Bella style)
st.markdown("""
    <style>
    /* 1. Oculta o menu padrão do Streamlit e o footer */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* 2. Estilo Global e Cor de Fundo do Header */
    .stApp {
        background-color: #f7f7f7; /* Fundo mais claro */
    }
    
    /* 3. Container customizado do Header (cor Magenta da Loja) */
    div.header-container {
        padding: 0px 0 0px 0; /* Remove padding vertical */
        background-color: #E91E63; /* Cor Magenta Forte */
        color: white;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;
        position: relative;
        z-index: 1000;
    }
    
    /* 4. Estilo dos botões/abas de Navegação (dentro do header) */
    .nav-button-group {
        display: flex;
        gap: 0;  
        align-items: flex-end; /* Alinha os botões na base da barra */
    }
    
    /* Estilo dos botões/abas individuais */
    div[data-testid^="stHorizontalBlock"] button {
        border-radius: 5px 5px 0 0;
        margin-right: 5px;
        transition: all 0.2s;
        min-width: 150px;
        height: 45px; /* Altura do botão */
        font-weight: bold;
        color: #E91E63;  
        border: 1px solid #ddd;
        border-bottom: none;
    }

    /* Estilo para botão INATIVO */
    div[data-testid^="stHorizontalBlock"] button {
        background-color: #f2f2f2;
        color: #880E4F; /* Rosa Escuro */
    }

    /* Estilo para botão ATIVO */
    div[data-testid^="stHorizontalBlock"] button.active-nav-button {
        background-color: white !important;
        border-color: #E91E63;
        color: #E91E63 !important; /* Cor principal */
        box-shadow: 0 -4px 6px rgba(0, 0, 0, 0.1);
    }

    /* Ajuste para centralizar o logo */
    .logo-container {
        padding: 10px 20px;
        /* CORREÇÃO: Removendo o fundo branco para que o PNG transparente combine com o fundo da página */
        background-color: transparent;  
    }
    
    /* Ajuste de cor do st.metric */
    div[data-testid="stMetricValue"] {
        color: #E91E63 !important;  
    }
    </style>
""", unsafe_allow_html=True)

# --- Definição das Páginas (Funções de renderização) ---
# ... (SUAS FUNÇÕES render_lancamento, render_cadastro, etc. VÊM AQUI, SEM MUDANÇAS)
def render_lancamento():
    """Renderiza a página de Lançamento (Venda/Resgate)."""
    
    st.header("Lançamento de Venda e Resgate de Cashback")
    st.markdown("---")
    
    operacao = st.radio("Selecione a Operação:", ["Lançar Nova Venda", "Resgatar Cashback"], key='op_selecionada')

    if operacao == "Lançar Nova Venda":
        st.subheader("Nova Venda (Cashback por Nível)")
        
        clientes_nomes = [''] + st.session_state.clientes['Nome'].tolist()
        cliente_selecionado = st.selectbox(
            "Nome da Cliente (Selecione ou digite para buscar):",  
            options=clientes_nomes,  
            index=0,
            key='nome_cliente_venda'
        )
        
        # 1. Variáveis de Nível
        nivel_cliente = 'Prata'
        cb_normal_rate = NIVEIS['Prata']['cashback_normal']
        cb_turbo_rate = NIVEIS['Prata']['cashback_turbo']
        gasto_acumulado = 0.00
        primeira_compra_feita = True 
        
        # 2. Busca e Calcula Nível/Benefícios (CORRIGIDO: Busca dados atualizados)
        if cliente_selecionado and cliente_selecionado in st.session_state.clientes['Nome'].values:
            cliente_data = st.session_state.clientes[st.session_state.clientes['Nome'] == cliente_selecionado].iloc[0]
            gasto_acumulado = cliente_data['Gasto Acumulado']
            primeira_compra_feita = cliente_data['Primeira Compra Feita']
            
            # Recalcula o nível com o gasto acumulado atual
            nivel_cliente, cb_normal_rate, cb_turbo_rate = calcular_nivel_e_beneficios(gasto_acumulado)

            # --- Exibição de Nível e Taxas ---
            
            # Sobrescreve para Indicação (se for a primeira compra)
            if not primeira_compra_feita and cliente_data['Indicado Por']:
                taxa_aplicada_ind = CASHBACK_INDICADO_PRIMEIRA_COMPRA
                st.info(f"✨ **INDICAÇÃO ATIVA!** Cliente na primeira compra com indicação. Cashback de **{int(taxa_aplicada_ind * 100)}%** aplicado.")
                cb_normal_rate = taxa_aplicada_ind
                cb_turbo_rate = taxa_aplicada_ind # Usa a mesma taxa para cashback de primeira compra

            
            col_info1, col_info2, col_info3 = st.columns(3)
            col_info1.metric("Nível Atual", nivel_cliente)
            col_info2.metric("Cashback Normal", f"{int(cb_normal_rate * 100)}%")
            if cb_turbo_rate > 0:
                col_info3.metric("Cashback Turbo", f"{int(cb_turbo_rate * 100)}%")
            else:
                col_info3.metric("Cashback Turbo", "Indisponível")
            
            # NOVO: Exibe o saldo disponível
            st.markdown(f"**Saldo de Cashback Disponível:** R$ {cliente_data['Cashback Disponível']:.2f}")
            st.markdown("---") # Separador visual

        
        # 3. MOVIDO PARA FORA DO FORM: Valor da Venda (para cálculo em tempo real)
        valor_venda = st.number_input("Valor da Venda (R$):", min_value=0.00, step=50.0, format="%.2f", key='valor_venda')
        
        # 🟢 VERIFICAÇÃO DE PRODUTOS TURBO ATIVOS
        produtos_ativos = get_produtos_turbo_ativos()
        
        venda_turbo = False
        if produtos_ativos:
            st.warning(f"⚠️ **PRODUTOS TURBO ATIVOS:** {', '.join(produtos_ativos)}", icon="⚡")
            
            # Só pergunta se a cliente tem direito a cashback turbo (Nível Ouro/Diamante ou Indicação)
            if cb_turbo_rate > 0:
                venda_turbo = st.checkbox(
                    "Esta venda contém **Produtos Turbo** (Aplica taxa de **" + f"{int(cb_turbo_rate * 100)}%" + "**)?", 
                    key='venda_turbo_check'
                )
            else:
                st.info("Cliente não possui benefício Turbo extra (Nível Prata ou Indicação já usada).")
        else:
             st.info("Nenhum produto turbo ativo no momento.")


        # CÁLCULO INSTANTÂNEO
        taxa_final = cb_turbo_rate if venda_turbo and cb_turbo_rate > 0 else cb_normal_rate
        cashback_calculado = st.session_state.valor_venda * taxa_final
        
        st.metric(label=f"Cashback a Gerar (Taxa Aplicada: {int(taxa_final * 100)}%):", value=f"R$ {cashback_calculado:.2f}")
        
        with st.form("form_venda", clear_on_submit=True):
            data_venda = st.date_input("Data da Venda:", value=date.today(), key='data_venda')
            submitted_venda = st.form_submit_button("Lançar Venda e Gerar Cashback")
            
            if submitted_venda:
                lancamento_valor_venda = st.session_state.valor_venda
                lancamento_cashback = lancamento_valor_venda * taxa_final
                
                if not cliente_selecionado:
                    st.error("Por favor, selecione o nome de uma cliente.")
                elif lancamento_valor_venda <= 0.00:
                    st.error("O valor da venda deve ser maior que R$ 0,00.")
                else:
                    lancar_venda(cliente_selecionado, lancamento_valor_venda, lancamento_cashback, data_venda, venda_turbo)

    elif operacao == "Resgatar Cashback":
        st.subheader("Resgate de Cashback")
        
        clientes_com_cashback = st.session_state.clientes[st.session_state.clientes['Cashback Disponível'] >= 20.00]
        clientes_options = [''] + clientes_com_cashback['Nome'].tolist()
        
        with st.form("form_resgate", clear_on_submit=True):
            cliente_resgate = st.selectbox("Cliente para Resgate:", options=clientes_options, key='nome_cliente_resgate')
            valor_venda_resgate = st.number_input("Valor da Venda Atual (para cálculo do limite de 50%):", min_value=0.01, step=50.0, format="%.2f", key='valor_venda_resgate')
            valor_resgate = st.number_input("Valor do Resgate (Mínimo R$20,00):", min_value=0.00, step=1.00, format="%.2f", key='valor_resgate')
            data_resgate = st.date_input("Data do Resgate:", value=date.today(), key='data_resgate')

            if cliente_resgate:
                saldo_atual = st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_resgate, 'Cashback Disponível'].iloc[0]
                st.info(f"Saldo Disponível para {cliente_resgate}: R$ {saldo_atual:.2f}")
                max_resgate_disp = valor_venda_resgate * 0.50
                st.warning(f"Resgate Máximo Permitido (50% da venda): R$ {max_resgate_disp:.2f}")

            submitted_resgate = st.form_submit_button("Confirmar Resgate")
            if submitted_resgate:
                if not cliente_resgate:
                    st.error("Por favor, selecione a cliente para resgate.")
                elif valor_resgate <= 0:
                    st.error("O valor do resgate deve ser maior que zero.")
                else:
                    saldo_atual = st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_resgate, 'Cashback Disponível'].iloc[0]
                    resgatar_cashback(cliente_resgate, valor_resgate, valor_venda_resgate, data_resgate, saldo_atual)

# --- Mapeamento das Páginas ---
PAGINAS = {
    "Home": render_home,
    "Lançamento": render_lancamento,
    "Cadastro": render_cadastro,
    "Produtos Turbo": render_produtos_turbo,
    "Relatórios": render_relatorios
}

# ... (outras funções render_... sem alterações)

# ==============================================================================
# EXECUÇÃO PRINCIPAL (LÓGICA DE CARREGAMENTO ATUALIZADA)
# ==============================================================================

# Garante que as variáveis de controle de UI existam
if 'editing_client' not in st.session_state: st.session_state.editing_client = False
if 'deleting_client' not in st.session_state: st.session_state.deleting_client = False
if 'valor_venda' not in st.session_state: st.session_state.valor_venda = 0.00
if "pagina_atual" not in st.session_state: st.session_state.pagina_atual = "Home"


# >>>>> LÓGICA DE CARREGAMENTO CENTRAL E CORRIGIDA <<<<<
# Verifica se os dataframes já foram carregados nesta sessão.
# Se não foram (ex: primeira execução ou após um salvar_dados), carrega do CSV.
if 'clientes' not in st.session_state:
    # Chama a função em cache que LÊ os arquivos e RETORNA os dataframes
    df_clientes, df_lancamentos, df_produtos_turbo = carregar_dados()

    # Popula o st.session_state com os dados frescos
    st.session_state.clientes = df_clientes
    st.session_state.lancamentos = df_lancamentos
    st.session_state.produtos_turbo = df_produtos_turbo


# --- Renderização da UI ---

# Renderiza o cabeçalho customizado no topo da página
render_header()

# Renderização do conteúdo da página selecionada
st.markdown('<div style="padding-top: 20px;">', unsafe_allow_html=True)
if st.session_state.pagina_atual in PAGINAS:
    PAGINAS[st.session_state.pagina_atual]()
st.markdown('</div>', unsafe_allow_html=True)
