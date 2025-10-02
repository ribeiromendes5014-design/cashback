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
        'cashback_turbo': 0.00, # Não tem
        'proximo_nivel': 'Ouro'
    },
    'Ouro': {
        # Corrigido: Ouro começa a partir de 200.01.
        'min_gasto': 200.01, 
        'max_gasto': 1000.00, 
        'cashback_normal': 0.07, # 7%
        'cashback_turbo': 0.10, # 10%
        'proximo_nivel': 'Diamante'
    },
    'Diamante': {
        # Corrigido: Diamante começa a partir de 1000.01.
        'min_gasto': 1000.01, 
        'max_gasto': float('inf'), 
        'cashback_normal': 0.15, # 15%
        'cashback_turbo': 0.20, # 20%
        'proximo_nivel': 'Max'
    }
}

# --- Configuração de Persistência (Puxa do st.secrets) ---
try:
    # 1. Tenta ler o formato PyGithub (separa OWNER/NAME)
    TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO_OWNER = st.secrets["REPO_OWNER"]
    REPO_NAME = st.secrets["REPO_NAME"]
    BRANCH = st.secrets.get("BRANCH", "main")
    PERSISTENCE_MODE = "GITHUB"
except KeyError:
    # 2. Tenta ler o formato [github] (repository completo)
    github_section = st.secrets.get("github")
    
    if github_section and github_section.get("token") and github_section.get("repository"):
        TOKEN = github_section["token"]
        repo_full = github_section["repository"]
        if "/" in repo_full:
            REPO_OWNER = repo_full.split("/")[0]
            REPO_NAME = repo_full.split("/")[1]
        else:
            REPO_OWNER = ""
            REPO_NAME = ""
        BRANCH = github_section.get("branch", "main")
        
        if REPO_OWNER and REPO_NAME:
            PERSISTENCE_MODE = "GITHUB"
        else:
            PERSISTENCE_MODE = "LOCAL"
    else:
        # Fallback se nenhuma das estruturas funcionar
        PERSISTENCE_MODE = "LOCAL"

# Define URL base se o modo for GITHUB
if PERSISTENCE_MODE == "GITHUB":
    URL_BASE_REPOS = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/"


# --- Configuração e Função do Telegram ---
try:
    TELEGRAM_BOT_ID = st.secrets["telegram"]["BOT_ID"]
    TELEGRAM_CHAT_ID = st.secrets["telegram"]["CHAT_ID"]
    # Adicionando o ID do Tópico/Thread (se existir)
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
    
    # Adiciona o ID do Tópico se configurado
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
        # Ao carregar, mantemos como dtype=str para evitar inferência errada inicial
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
    
    # Lógica de formatação de datas
    if 'Data' in df_temp.columns or 'Data Início' in df_temp.columns or 'Data Fim' in df_temp.columns:
        # Formata datas para o CSV
        if 'Data' in df_temp.columns:
             df_temp['Data'] = pd.to_datetime(df_temp['Data'], errors='coerce').apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '')
        if 'Data Início' in df_temp.columns:
             df_temp['Data Início'] = pd.to_datetime(df_temp['Data Início'], errors='coerce').apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '')
        if 'Data Fim' in df_temp.columns:
             df_temp['Data Fim'] = pd.to_datetime(df_temp['Data Fim'], errors='coerce').apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '')

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
    """Salva os DataFrames de volta nos arquivos CSV, priorizando o GitHub. Limpa o cache."""
    
    # Limpa o cache para forçar a releitura dos CSVs.
    st.cache_data.clear() 

    # Incrementa a chave de estado para invalidar o cache pela assinatura da função.
    if 'data_version' not in st.session_state:
        st.session_state.data_version = 0
    st.session_state.data_version += 1

    if PERSISTENCE_MODE == "GITHUB":
        salvar_dados_no_github(st.session_state.clientes, CLIENTES_CSV, "AUTOSAVE: Atualizando clientes e saldos.")
        salvar_dados_no_github(st.session_state.lancamentos, LANÇAMENTOS_CSV, "AUTOSAVE: Atualizando histórico de lançamentos.")
        salvar_dados_no_github(st.session_state.produtos_turbo, PRODUTOS_TURBO_CSV, "AUTOSAVE: Atualizando produtos turbo.")
    else: # Modo LOCAL
        st.session_state.clientes.to_csv(CLIENTES_CSV, index=False)
        st.session_state.lancamentos.to_csv(LANÇAMENTOS_CSV, index=False)
        st.session_state.produtos_turbo.to_csv(PRODUTOS_TURBO_CSV, index=False)
        
# Variável global para auxiliar a função de carregamento a garantir todas as colunas
colunas_esperadas = [] 

def carregar_dados_do_csv(file_path, df_columns):
    """Lógica para carregar CSV local ou do GitHub, retornando o DF."""
    df = pd.DataFrame(columns=df_columns)  
    
    if PERSISTENCE_MODE == "GITHUB":
        url_raw = f"{URL_BASE_REPOS}{file_path}"
        df_carregado = load_csv_github(url_raw)
        if df_carregado is not None:
            df = df_carregado
        
    elif os.path.exists(file_path): 
        try: 
            df = pd.read_csv(file_path, dtype=str) # Leitura sempre como string
        except pd.errors.EmptyDataError:
            pass
            
    # Garante que todas as colunas existem e inicializa valores padrão
    for col in df_columns:
        if col not in df.columns: 
            df[col] = "" # Inicia como string vazia
        
    # CORREÇÃO: Preenche valores NaN/vazios em colunas que sabemos que devem ter um valor padrão
    if 'Cashback Disponível' in df.columns:
        df['Cashback Disponível'] = df['Cashback Disponível'].fillna('0.0')
    if 'Gasto Acumulado' in df.columns:
        df['Gasto Acumulado'] = df['Gasto Acumulado'].fillna('0.0')
    if 'Nivel Atual' in df.columns:
        df['Nivel Atual'] = df['Nivel Atual'].fillna('Prata')
    if 'Primeira Compra Feita' in df.columns:
        df['Primeira Compra Feita'] = df['Primeira Compra Feita'].fillna('False')
    if 'Venda Turbo' in df.columns:
        df['Venda Turbo'] = df['Venda Turbo'].fillna('Não')
    
    return df[df_columns]

@st.cache_data(show_spinner="Carregando dados...")
def carregar_dados(data_version_key): # <-- CHAVE DE VERSÃO ADICIONADA
    """Tenta carregar os DataFrames, priorizando o GitHub se configurado."""
    
    # 1. CLIENTES: Colunas
    CLIENTES_COLS = [
        'Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível',
        'Gasto Acumulado', 'Nivel Atual', 'Indicado Por', 'Primeira Compra Feita'
    ]
    global colunas_esperadas # Define a variável global para uso em carregar_dados_do_csv
    colunas_esperadas = CLIENTES_COLS
    st.session_state.clientes = carregar_dados_do_csv(CLIENTES_CSV, CLIENTES_COLS)
    
    # 2. LANÇAMENTOS: Colunas
    LANÇAMENTOS_COLS = ['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback', 'Venda Turbo']
    colunas_esperadas = LANÇAMENTOS_COLS
    st.session_state.lancamentos = carregar_dados_do_csv(LANÇAMENTOS_CSV, LANÇAMENTOS_COLS)
    
    # 3. PRODUTOS TURBO: Colunas
    PRODUTOS_TURBO_COLS = ['Nome Produto', 'Data Início', 'Data Fim', 'Ativo']
    colunas_esperadas = PRODUTOS_TURBO_COLS
    st.session_state.produtos_turbo = carregar_dados_do_csv(PRODUTOS_TURBO_CSV, PRODUTOS_TURBO_COLS)

    
    # --- Inicialização e Tipagem Clientes (CORRIGIDA) ---
    if 'clientes' not in st.session_state or st.session_state.clientes.empty:
        st.session_state.clientes = pd.DataFrame(columns=CLIENTES_COLS)
        st.session_state.clientes.loc[0] = ['Cliente Exemplo', 'Primeiro Cliente', '99999-9999', 50.00, 0.00, 'Prata', '', False]
        
    # FORÇA a conversão de string para o tipo correto
    st.session_state.clientes['Cashback Disponível'] = pd.to_numeric(
        st.session_state.clientes['Cashback Disponível'], errors='coerce'
    ).fillna(0.0)
    st.session_state.clientes['Gasto Acumulado'] = pd.to_numeric(
        st.session_state.clientes['Gasto Acumulado'], errors='coerce'
    ).fillna(0.0)
    # Converte 'True'/'False' string para bool
    st.session_state.clientes['Primeira Compra Feita'] = st.session_state.clientes['Primeira Compra Feita'].astype(str).str.lower().map({'true': True, 'false': False}).fillna(False).astype(bool)
    # Preenche strings vazias em Nivel Atual com 'Prata' (caso venha vazia)
    st.session_state.clientes['Nivel Atual'] = st.session_state.clientes['Nivel Atual'].fillna('Prata')


    # --- Tipagem Lançamentos ---
    if not st.session_state.lancamentos.empty:
        st.session_state.lancamentos['Data'] = pd.to_datetime(st.session_state.lancamentos['Data'], errors='coerce').dt.date
        # Garante que 'Venda Turbo' seja string ou booleano para evitar erro de tipo na exibição
        st.session_state.lancamentos['Venda Turbo'] = st.session_state.lancamentos['Venda Turbo'].astype(str).replace({'True': 'Sim', 'False': 'Não', '': 'Não'}).fillna('Não')

    # --- Tipagem Produtos Turbo ---
    if 'produtos_turbo' not in st.session_state:
        st.session_state.produtos_turbo = pd.DataFrame(columns=PRODUTOS_TURBO_COLS)
        
    if not st.session_state.produtos_turbo.empty:
        st.session_state.produtos_turbo['Data Início'] = pd.to_datetime(st.session_state.produtos_turbo['Data Início'], errors='coerce').dt.date
        st.session_state.produtos_turbo['Data Fim'] = pd.to_datetime(st.session_state.produtos_turbo['Data Fim'], errors='coerce').dt.date
        # Garante que 'Ativo' seja booleano
        st.session_state.produtos_turbo['Ativo'] = st.session_state.produtos_turbo['Ativo'].astype(str).str.lower().map({'true': True, 'false': False}).fillna(False).astype(bool)
    

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
    
    # CORREÇÃO: Força o salvamento dos DataFrames limpos no CSV antes do rerun
    salvar_dados()
    
    st.session_state.deleting_client = False
    st.success(f"Cliente '{nome_cliente}' e todos os seus lançamentos foram excluídos.")
    # Força o recarregamento, que agora lerá o CSV atualizado
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

    # IMPORTANTE: Pegar os dados ANTES de atualizar
    cliente_data = st.session_state.clientes.loc[idx_cliente].iloc[0]
    
    # ------------------------------------
    # 1. ATUALIZAÇÕES DO CLIENTE
    # ------------------------------------
    
    # Atualiza o saldo do cliente
    st.session_state.clientes.loc[idx_cliente, 'Cashback Disponível'] += valor_cashback
    
    # Atualiza o gasto acumulado
    st.session_state.clientes.loc[idx_cliente, 'Gasto Acumulado'] += valor_venda
    
    # Recalcula o Nível com o novo gasto acumulado (CORREÇÃO DE LÓGICA DE NÍVEL)
    novo_gasto_acumulado = st.session_state.clientes.loc[idx_cliente, 'Gasto Acumulado'].iloc[0]
    novo_nivel, _, _ = calcular_nivel_e_beneficios(novo_gasto_acumulado)
    st.session_state.clientes.loc[idx_cliente, 'Nivel Atual'] = novo_nivel
    
    # Marca a primeira compra como feita
    st.session_state.clientes.loc[idx_cliente, 'Primeira Compra Feita'] = True
    
    # ------------------------------------
    # 2. LOGICA DO INDIQUE E GANHE (BÔNUS PARA O INDICADOR)
    # ------------------------------------
    bonus_para_indicador = 0.0
    
    # Apenas se for a PRIMEIRA compra E houver um indicador
    if not cliente_data['Primeira Compra Feita'] and cliente_data['Indicado Por']:
        indicador_nome = cliente_data['Indicado Por']
        idx_indicador = st.session_state.clientes[st.session_state.clientes['Nome'] == indicador_nome].index
        
        if not idx_indicador.empty:
            bonus_para_indicador = valor_venda * BONUS_INDICACAO_PERCENTUAL # 5% do valor da venda do indicado
            st.session_state.clientes.loc[idx_indicador, 'Cashback Disponível'] += bonus_para_indicador
            
            # Adiciona o lançamento do bônus ao histórico
            lancamento_bonus = pd.DataFrame({
                'Data': [data_venda],
                'Cliente': [indicador_nome],
                'Tipo': ['Bônus Indicação'],
                'Valor Venda/Resgate': [valor_venda],
                'Valor Cashback': [bonus_para_indicador],
                'Venda Turbo': ['Não']
            })
            st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, lancamento_bonus], ignore_index=True)
            st.success(f"🎁 Bônus de Indicação de R$ {bonus_para_indicador:.2f} creditado para **{indicador_nome}**!")


    # ------------------------------------
    # 3. REGISTRA O LANÇAMENTO E SALVA
    # ------------------------------------
    novo_lancamento = pd.DataFrame({
        'Data': [data_venda],
        'Cliente': [cliente_nome],
        'Tipo': ['Venda'],
        'Valor Venda/Resgate': [valor_venda],
        'Valor Cashback': [valor_cashback],
        'Venda Turbo': ['Sim' if venda_turbo_selecionada else 'Não'] # NOVO CAMPO
    })
    st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, novo_lancamento], ignore_index=True)
    
    # SALVA E FORÇA O RECARREGAMENTO DO CACHE PARA ATUALIZAR A TELA
    salvar_dados()  
    st.success(f"Venda de R$ {valor_venda:.2f} lançada para **{cliente_nome}** ({novo_nivel}). Cashback de R$ {valor_cashback:.2f} adicionado.")

    # 4. Lógica de Envio para o Telegram (MANTIDO)
    if TELEGRAM_ENABLED:
        
        # Filtra SÓ as vendas (incluindo a atual)
        vendas_do_cliente = st.session_state.lancamentos[
            (st.session_state.lancamentos['Cliente'] == cliente_nome) & 
            (st.session_state.lancamentos['Tipo'] == 'Venda')
        ].copy()
        
        # Pega o NÚMERO TOTAL DE VENDAS
        numero_total_vendas = len(vendas_do_cliente)
        
        # Obtém o saldo atualizado (pós-salvamento)
        saldo_atualizado = st.session_state.clientes.loc[
            st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'
        ].iloc[0]
        
        # --- Fuso Horário Brasil ---
        fuso_horario_brasil = pytz.timezone('America/Sao_Paulo')
        agora_brasil = datetime.now(fuso_horario_brasil)
        data_hora_lancamento = agora_brasil.strftime('%d/%m/%Y às %H:%M')
        
        # Formatação de valores (R$ 1.000,00)
        cashback_ganho_str = f"R$ {valor_cashback:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        saldo_atual_str = f"R$ {saldo_atualizado:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        # Monta a mensagem final completa, adaptada para NÍVEL
        mensagem_telegram = (
            # --- PARTE 1: Introdução sobre a Novidade do Programa de Fidelidade ---
            "✨ Novidade imperdível na Doce&Bella! ✨\n\n"
            "Agora você pode aproveitar ainda mais as suas compras favoritas com o nosso Programa de Fidelidade 🛍💖\n\n"
            f"Você está no **NÍVEL {novo_nivel.upper()}**!\n\n"
            
            f"--- *Seu Saldo Atualizado* ---\n"
            f"🗓️ **Data/Hora:** *{data_hora_lancamento}*\n"
            f"💰 **Saldo Atual:** *{saldo_atual_str}*\n"
            f"🛒 **Total de Compras:** *{numero_total_vendas}*\n"
            f"----------------------------------\n\n"
            
            f"✨ *COMO USAR SEU CRÉDITO NA DOCE&BELLA*\n"
            f"1. **Limite de Uso:** Você pode usar até *50%* do valor total da sua nova compra.\n"
            f"2. **Saldo Mínimo:** Para resgatar, seu saldo deve ser de, no mínimo, *R$ 20,00*.\n\n"
            
            f"📞 *PRECISA DE AJUDA OU QUER CONSULTAR SEU SALDO?*\n"
            f"Basta chamar a **Doce&Bella** pelo ZAP! 💬\n\n"
            
            f"🚨 Dica: Salve nosso número na sua agenda para não perder as promoções e novidades!"
        )
        
        enviar_mensagem_telegram(mensagem_telegram)

def resgatar_cashback(cliente_nome, valor_resgate, valor_venda_atual, data_resgate, saldo_disponivel):
    """
    Processa o resgate de cashback, salva os dados e envia notificação ao Telegram.
    Atenção: A variável 'saldo_disponivel' é o saldo antes do resgate.
    """
    
    # --- 1. Validações Iniciais ---
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
        
    # --- 2. Processa a Transação ---
    st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'] -= valor_resgate
    
    # Obtém o saldo ATUALIZADO (após a dedução) antes de salvar
    saldo_apos_resgate = st.session_state.clientes.loc[
        st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'
    ].iloc[0]
    
    novo_lancamento = pd.DataFrame({
        'Data': [data_resgate],
        'Cliente': [cliente_nome],
        'Tipo': ['Resgate'],
        'Valor Venda/Resgate': [valor_venda_atual],
        'Valor Cashback': [-valor_resgate],
        'Venda Turbo': ['Não'] # Resgate não é turbo
    })
    st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, novo_lancamento], ignore_index=True)
    
    salvar_dados()  
    st.success(f"Resgate de R$ {valor_resgate:.2f} realizado com sucesso para {cliente_nome}.")

    # --- 3. Lógica de Envio para o Telegram (MANTIDA) ---
    if TELEGRAM_ENABLED:
        
        # --- Fuso Horário Brasil ---
        fuso_horario_brasil = pytz.timezone('America/Sao_Paulo')
        agora_brasil = datetime.now(fuso_horario_brasil)
        data_hora_lancamento = agora_brasil.strftime('%d/%m/%Y às %H:%M')
        
        # Formatação de valores (R$ 1.000,00)
        valor_resgate_str = f"R$ {valor_resgate:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        saldo_apos_resgate_str = f"R$ {saldo_apos_resgate:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        # Monta a mensagem final no formato solicitado
        mensagem_telegram = (
            f"🛒 *Loja Doce&Bella: RESGATE DE CASHBACK*\n\n"
            f"Você (*{cliente_nome}*) resgatou *{valor_resgate_str}* em *{data_hora_lancamento}*.\n\n"
            f"❤ Seu saldo em conta é de *{saldo_apos_resgate_str}*.\n\n"
            f"Obrigado pela preferência! :)\n\n"
            f"========================="
        )
        
        enviar_mensagem_telegram(mensagem_telegram)


# ==============================================================================
# ESTRUTURA E LAYOUT DO STREAMLIT
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

    /* Estilo para destaque de Nível */
    .nivel-diamante {
        color: #3f51b5; /* Azul */
        font-weight: bold;
    }
    .nivel-ouro {
        color: #ffc107; /* Amarelo */
        font-weight: bold;
    }
    .nivel-prata {
        color: #607d8b; /* Cinza */
        font-weight: bold;
    }

    </style>
""", unsafe_allow_html=True)

# --- Definição das Páginas (Funções de renderização) ---

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
        # Se o checkbox for marcado E a taxa for > 0, usa a taxa turbo. Caso contrário, usa a taxa normal.
        taxa_final = cb_turbo_rate if venda_turbo and cb_turbo_rate > 0 else cb_normal_rate
        cashback_calculado = st.session_state.valor_venda * taxa_final
        
        # EXIBIÇÃO INSTANTÂNEA
        st.metric(label=f"Cashback a Gerar (Taxa Aplicada: {int(taxa_final * 100)}%):", value=f"R$ {cashback_calculado:.2f}")
        
        with st.form("form_venda", clear_on_submit=True):
            
            st.caption(f"Cliente: **{cliente_selecionado}** | Venda: **R$ {st.session_state.valor_venda:.2f}** | Taxa: **{int(taxa_final * 100)}%**")
            
            data_venda = st.date_input("Data da Venda:", value=date.today(), key='data_venda')
            
            submitted_venda = st.form_submit_button("Lançar Venda e Gerar Cashback")
            
            if submitted_venda:
                # Usa os valores recalculados no momento da submissão
                lancamento_valor_venda = st.session_state.valor_venda
                lancamento_cashback = lancamento_valor_venda * taxa_final
                
                if cliente_selecionado == '':
                    st.error("Por favor, selecione o nome de uma cliente.")
                elif lancamento_valor_venda <= 0.00:
                    st.error("O valor da venda deve ser maior que R$ 0,00.")
                elif cliente_selecionado not in st.session_state.clientes['Nome'].values:
                    st.error("Cliente não encontrado. Por favor, cadastre-o primeiro na seção 'Cadastro'.")
                else:
                    lancar_venda(cliente_selecionado, lancamento_valor_venda, lancamento_cashback, data_venda, venda_turbo)

    elif operacao == "Resgatar Cashback":
        st.subheader("Resgate de Cashback")
        
        clientes_com_cashback = st.session_state.clientes[st.session_state.clientes['Cashback Disponível'] >= 20.00].copy()
        clientes_options = [''] + clientes_com_cashback['Nome'].tolist()
        
        with st.form("form_resgate", clear_on_submit=True):
            
            cliente_resgate = st.selectbox(
                "Cliente para Resgate:",  
                options=clientes_options,
                index=0,
                key='nome_cliente_resgate'
            )
            
            saldo_atual = 0.00
            
            valor_venda_resgate = st.number_input(
                "Valor da Venda Atual (para cálculo do limite de 50%):",  
                min_value=0.01,  
                step=50.0,  
                format="%.2f",  
                key='valor_venda_resgate'
            )
            
            valor_resgate = st.number_input(
                "Valor do Resgate (Mínimo R$20,00):",  
                min_value=0.00,  
                step=1.00,  
                format="%.2f",  
                key='valor_resgate'
            )
            
            data_resgate = st.date_input("Data do Resgate:", value=date.today(), key='data_resgate')

            if cliente_resgate != '':
                if cliente_resgate in st.session_state.clientes['Nome'].values:
                    saldo_atual = st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_resgate, 'Cashback Disponível'].iloc[0]
                    st.info(f"Saldo Disponível para {cliente_resgate}: R$ {saldo_atual:.2f}")
                    
                    max_resgate_disp = valor_venda_resgate * 0.50
                    st.warning(f"Resgate Máximo Permitido (50% da venda): R$ {max_resgate_disp:.2f}")
                else:
                    st.warning("Cliente não encontrado ou saldo insuficiente para resgate.")
            else:
                st.info("Selecione um cliente acima para visualizar o saldo disponível e limites de resgate.")

            submitted_resgate = st.form_submit_button("Confirmar Resgate")
            
            if submitted_resgate:
                if cliente_resgate == '':
                    st.error("Por favor, selecione a cliente para resgate.")
                elif valor_resgate <= 0:
                    st.error("O valor do resgate deve ser maior que zero.")
                else:
                    # Recalcula saldo atual para garantir que o saldo_disponivel passado à função esteja correto
                    if cliente_resgate in st.session_state.clientes['Nome'].values:
                        saldo_atual = st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_resgate, 'Cashback Disponível'].iloc[0]
                        resgatar_cashback(cliente_resgate, valor_resgate, valor_venda_resgate, data_resgate, saldo_atual)
                    else:
                        st.error("Erro ao calcular saldo. Cliente não encontrado.")

def render_produtos_turbo():
    """Renderiza a página de Cadastro e Gestão de Produtos Turbo."""
    st.header("Gestão de Produtos Turbo (Cashback Extra)")
    st.markdown("---")

    # ------------------
    # --- NOVO CADASTRO ---
    # ------------------
    with st.form("form_cadastro_produto", clear_on_submit=True):
        st.subheader("Cadastrar Novo Produto Turbo")
        nome_produto = st.text_input("Nome do Produto (Ex: Linha Cabelo X)", key='cadastro_produto_nome')
        col_data_inicio, col_data_fim = st.columns(2)
        with col_data_inicio:
            data_inicio = st.date_input("Data de Início da Promoção:", value=date.today(), key='cadastro_data_inicio')
        with col_data_fim:
            data_fim = st.date_input("Data de Fim da Promoção:", value=date.today(), key='cadastro_data_fim')
        
        submitted_cadastro = st.form_submit_button("Cadastrar Produto")
        
        if submitted_cadastro:
            if nome_produto and data_inicio and data_fim:
                if data_inicio > data_fim:
                     st.error("A Data de Início não pode ser maior que a Data de Fim.")
                else:
                    adicionar_produto_turbo(nome_produto.strip(), data_inicio, data_fim)
            else:
                st.error("Preencha todos os campos obrigatórios.")

    st.markdown("---")
    
    # --------------------------------
    # --- VISUALIZAÇÃO E GESTÃO ---
    # --------------------------------
    st.subheader("Produtos Cadastrados")
    
    if st.session_state.produtos_turbo.empty:
        st.info("Nenhum produto turbo cadastrado ainda.")
        return

    # Processa o DF para exibição
    df_display = st.session_state.produtos_turbo.copy()
    
    # Adiciona a coluna Status dinamicamente
    hoje = date.today()
    df_display['Status'] = df_display.apply(
        lambda row: 'ATIVO' if (row['Data Início'] is not pd.NaT and row['Data Fim'] is not pd.NaT and row['Data Início'] <= hoje and row['Data Fim'] >= hoje) else 'INATIVO',
        axis=1
    )
    
    st.dataframe(df_display[['Nome Produto', 'Data Início', 'Data Fim', 'Status']], use_container_width=True, hide_index=True)
    
    # --- Opções de Exclusão ---
    st.markdown("---")
    st.subheader("Excluir Produto")
    
    produtos_para_operacao = [''] + st.session_state.produtos_turbo['Nome Produto'].tolist()
    produto_selecionado = st.selectbox(
        "Selecione o Produto para Excluir:",
        options=produtos_para_operacao,
        index=0,
        key='produto_selecionado_exclusao'
    )

    if produto_selecionado:
        st.error(f"Deseja realmente excluir **{produto_selecionado}**?")
        if st.button(f"🔴 Confirmar Exclusão de {produto_selecionado}", type='primary', key='confirmar_exclusao_produto'):
            excluir_produto_turbo(produto_selecionado)


def render_cadastro():
    """Renderiza a página de Cadastro e Gestão de Clientes."""
    
    st.header("Cadastro de Clientes e Gestão")
    
    # ------------------
    # --- NOVO CADASTRO ---
    # ------------------
    st.subheader("Novo Cliente")
    
    # ----------------------------------------------
    # PROGRAMA INDIQUE E GANHE (FORA DO FORM PARA REATIVIDADE)
    # ----------------------------------------------
    
    # Inicializa o estado do checkbox se ainda não existir
    if 'is_indicado_check' not in st.session_state:
         st.session_state.is_indicado_check = False
         
    # Checkbox para indicar se houve indicação
    st.checkbox(
        "Esta cliente foi indicada por outra?", 
        value=st.session_state.get('is_indicado_check', False), 
        key='is_indicado_check'
    )
    
    indicado_por = ''
    
    if st.session_state.is_indicado_check:
        st.markdown("---")
        st.markdown("##### 🎁 Programa Indique e Ganhe")
        
        clientes_indicadores = [''] + st.session_state.clientes['Nome'].tolist()
        
        # Selectbox para o indicador (IMEDIATA APARIÇÃO)
        indicado_por = st.selectbox(
            "Nome da Cliente Indicadora:", 
            options=clientes_indicadores, 
            key='indicador_nome_select', # Salva o nome do indicador no session state
            index=0
        )
        
        # Mensagem de benefício
        bonus_pct = int(BONUS_INDICACAO_PERCENTUAL * 100)
        cashback_indicado_pct = int(CASHBACK_INDICADO_PRIMEIRA_COMPRA * 100)
        
        if indicado_por:
            st.success(
                f"**Bônus Indicação:** A cliente **{indicado_por}** receberá **{bonus_pct}%** do valor da primeira compra, creditado após o lançamento da venda desta nova cliente. "
                f"A nova cliente receberá **{cashback_indicado_pct}%** de cashback na primeira compra!"
            )
        else:
             st.info(
                f"A nova cliente receberá **{cashback_indicado_pct}%** de cashback na primeira compra! "
                f"Selecione a cliente indicadora acima para que ela receba o bônus de **{bonus_pct}%**."
            )
    
    # ----------------------------------------------
    # --- INPUTS DE DADOS PESSOAIS DENTRO DO FORM ---
    # ----------------------------------------------
    with st.form("form_cadastro_cliente", clear_on_submit=True):
        st.markdown("---")
        st.markdown("##### Dados Pessoais") # Nova sub-seção para organizar
        
        col_nome, col_tel = st.columns(2)
        with col_nome:
            nome = st.text_input("Nome da Cliente (Obrigatório):", key='cadastro_nome')
        with col_tel:
            telefone = st.text_input("Número de Telefone:", help="Ex: 99999-9999", key='cadastro_telefone')
            
        apelido = st.text_input("Apelido ou Descrição (Opcional):", key='cadastro_apelido')
        
        
        submitted_cadastro = st.form_submit_button("Cadastrar Cliente")
        
        
        if submitted_cadastro:
            # Captura o valor final do indicador do session state, que foi atualizado fora do form.
            # Verifica se o checkbox foi marcado ANTES de tentar buscar o valor do seletor
            indicado_por_final = st.session_state.get('indicador_nome_select', '') if st.session_state.get('is_indicado_check', False) else ''
            
            # Use as keys do session state para pegar os dados do form
            if st.session_state.cadastro_nome:
                cadastrar_cliente(
                    st.session_state.cadastro_nome.strip(), 
                    st.session_state.cadastro_apelido.strip(), 
                    st.session_state.cadastro_telefone.strip(), 
                    indicado_por_final.strip()
                )
            else:
                st.error("O campo 'Nome da Cliente' é obrigatório.")

    st.markdown("---")
    
    # --------------------------------
    # --- EDIÇÃO E EXCLUSÃO ---
    # --------------------------------
    st.subheader("Operações de Edição e Exclusão")
    
    clientes_para_operacao = [''] + st.session_state.clientes['Nome'].tolist()
    
    with st.container(border=True):
        cliente_selecionado_operacao = st.selectbox(
            "Selecione a Cliente para Editar ou Excluir:",
            options=clientes_para_operacao,
            index=0,
            key='cliente_selecionado_operacao',
            help="Selecione um nome para carregar o formulário de edição/exclusão abaixo."
        )

    if cliente_selecionado_operacao:
        cliente_data = st.session_state.clientes[
            st.session_state.clientes['Nome'] == cliente_selecionado_operacao
        ].iloc[0]
        
        st.markdown("##### Dados do Cliente Selecionado")

        col_edicao, col_exclusao = st.columns([1, 1])
        
        with col_edicao:
            if st.button("✏️ Editar Cadastro", use_container_width=True, key='btn_editar'):
                st.session_state.editing_client = cliente_selecionado_operacao
                st.session_state.deleting_client = False  
                st.rerun()  
        
        with col_exclusao:
            if st.button("🗑️ Excluir Cliente", use_container_width=True, key='btn_excluir', type='primary'):
                st.session_state.deleting_client = cliente_selecionado_operacao
                st.session_state.editing_client = False  
                st.rerun()  
        
        st.markdown("---")
        
        if st.session_state.editing_client == cliente_selecionado_operacao:
            st.subheader(f"Editando: {cliente_selecionado_operacao}")
            
            with st.form("form_edicao_cliente", clear_on_submit=False):
                
                novo_nome = st.text_input("Nome (Chave de Identificação):",  
                                          value=cliente_data['Nome'],  
                                          key='edicao_nome')
                
                novo_apelido = st.text_input("Apelido ou Descrição:",  
                                             value=cliente_data['Apelido/Descrição'],  
                                             key='edicao_apelido')
                
                novo_telefone = st.text_input("Número de Telefone:",  
                                              value=cliente_data['Telefone'],  
                                              key='edicao_telefone')
                
                st.info(f"Cashback Disponível: R$ {cliente_data['Cashback Disponível']:.2f} (Não editável)")

                submitted_edicao = st.form_submit_button("✅ Concluir Edição", use_container_width=True, type="secondary")
            
            if submitted_edicao:
                editar_cliente(cliente_selecionado_operacao, st.session_state.edicao_nome.strip(), st.session_state.edicao_apelido.strip(), st.session_state.edicao_telefone.strip())
            
            col_concluir_placeholder, col_cancelar = st.columns(2)
            
            with col_cancelar:
                if st.button("❌ Cancelar Edição", use_container_width=True, type='primary', key='cancelar_edicao_btn_final'):
                    st.session_state.editing_client = False
                    st.rerun()
        
        elif st.session_state.deleting_client == cliente_selecionado_operacao:
            st.error(f"ATENÇÃO: Você está prestes a excluir **{cliente_selecionado_operacao}**.")
            st.warning("Esta ação é irreversível e removerá todos os lançamentos de venda/resgate associados a esta cliente.")
            
            col_confirma, col_cancela_del = st.columns(2)
            with col_confirma:
                if st.button(f"🔴 Tenho Certeza! Excluir {cliente_selecionado_operacao}", use_container_width=True, key='confirmar_exclusao', type='primary'):
                    excluir_cliente(cliente_selecionado_operacao)
            with col_cancela_del:
                if st.button("↩️ Cancelar Exclusão", use_container_width=True, key='cancelar_exclusao'):
                    st.session_state.deleting_client = False
                    st.rerun()  
        
    st.markdown("---")
    st.subheader("Clientes Cadastrados (Visualização Completa)")
    # Corrigido: As colunas Gasto Acumulado, Cashback Disponível e Nível Atual serão exibidas corretamente agora
    st.dataframe(st.session_state.clientes.drop(columns=['Primeira Compra Feita']), hide_index=True, use_container_width=True) # Oculta o Booleano

def render_relatorios():
    """Renderiza a página de Relatórios e Rankings."""
    
    st.header("Relatórios e Rankings")
    st.markdown("---")
    
    # --------------------------------
    # --- RANKING POR NÍVEIS ---
    # --------------------------------
    st.subheader("💎 Ranking de Níveis de Fidelidade")
    
    # Cria uma cópia e calcula o Nível na hora
    df_niveis = st.session_state.clientes.copy()
    
    # Garante que o nível e o gasto estão atualizados
    df_niveis['Nivel Atual'] = df_niveis['Gasto Acumulado'].apply(lambda x: calcular_nivel_e_beneficios(x)[0])
    
    # Calcula quanto falta para o próximo nível
    df_niveis['Falta para Próximo Nível'] = df_niveis.apply(
        lambda row: calcular_falta_para_proximo_nivel(row['Gasto Acumulado'], row['Nivel Atual']), 
        axis=1
    )
    
    # Ordena por Nível (Diamante > Ouro > Prata) e depois por Gasto Acumulado
    ordenacao_nivel = {'Diamante': 3, 'Ouro': 2, 'Prata': 1}
    df_niveis['Ordem'] = df_niveis['Nivel Atual'].map(ordenacao_nivel)
    df_niveis = df_niveis.sort_values(by=['Ordem', 'Gasto Acumulado'], ascending=[False, False])
    
    df_display = df_niveis[['Nome', 'Nivel Atual', 'Gasto Acumulado', 'Falta para Próximo Nível']].reset_index(drop=True)
    df_display.columns = ['Cliente', 'Nível', 'Gasto Acumulado (R$)', 'Falta para Próximo Nível (R$)']
    
    # Formatação para R$
    df_display['Gasto Acumulado (R$)'] = df_display['Gasto Acumulado (R$)'].map('R$ {:.2f}'.format)
    df_display['Falta para Próximo Nível (R$)'] = df_display['Falta para Próximo Nível (R$)'].map('R$ {:.2f}'.format)
    
    df_display.index += 1
    st.dataframe(df_display, hide_index=False, use_container_width=True)
    
    # Explicação dos Níveis
    st.markdown("""
        **Níveis:**
        - **Prata:** Até R$ 200,00 gastos (3% cashback)
        - **Ouro:** R$ 200,01 a R$ 1.000,00 gastos (7% cashback normal / 10% turbo)
        - **Diamante:** Acima de R$ 1.000,01 gastos (15% cashback normal / 20% turbo)
    """)
    st.markdown("---")


    # --- Ranking de Cashback ---
    st.subheader("💰 Ranking: Maior Saldo de Cashback Disponível")
    ranking_cashback = st.session_state.clientes.sort_values(by='Cashback Disponível', ascending=False).reset_index(drop=True)
    ranking_cashback.index += 1  
    st.dataframe(ranking_cashback[['Nome', 'Cashback Disponível']].head(10), use_container_width=True)
    st.markdown("---")


    # --- Ranking de Maior Volume de Compras ---
    st.subheader("🛒 Ranking: Maior Volume de Compras (Gasto Acumulado Total)")
    
    # Usando a coluna 'Gasto Acumulado' diretamente que está sempre atualizada
    ranking_compras = st.session_state.clientes[['Nome', 'Gasto Acumulado']].sort_values(by='Gasto Acumulado', ascending=False).reset_index(drop=True)
    ranking_compras.columns = ['Cliente', 'Total Compras (R$)']
    ranking_compras['Total Compras (R$)'] = ranking_compras['Total Compras (R$)'].map('R$ {:.2f}'.format)
    ranking_compras.index += 1
    st.dataframe(ranking_compras.head(10), hide_index=False, use_container_width=True)

    st.markdown("---")
    
    # --- Histórico de Lançamentos ---
    st.subheader("📄 Histórico de Lançamentos")
    
    col_data, col_tipo = st.columns(2)
    with col_data:
        data_selecionada = st.date_input("Filtrar por Data:", value=None)
    with col_tipo:
        # Adicionado o Bônus de Indicação
        tipo_selecionado = st.selectbox("Filtrar por Tipo:", ['Todos', 'Venda', 'Resgate', 'Bônus Indicação'], index=0)

    df_historico = st.session_state.lancamentos.copy()
    
    if not df_historico.empty:
        if data_selecionada:
            df_historico['Data'] = df_historico['Data'].astype(str)
            data_selecionada_str = str(data_selecionada)
            df_historico = df_historico[df_historico['Data'] == data_selecionada_str]

        if tipo_selecionado != 'Todos':
            df_historico = df_historico[df_historico['Tipo'] == tipo_selecionado]

        if not df_historico.empty:
            df_historico['Valor Venda/Resgate'] = pd.to_numeric(df_historico['Valor Venda/Resgate'], errors='coerce').fillna(0).map('R$ {:.2f}'.format)
            df_historico['Valor Cashback'] = pd.to_numeric(df_historico['Valor Cashback'], errors='coerce').fillna(0).map('R$ {:.2f}'.format)
            
            # Reorganiza as colunas para incluir 'Venda Turbo'
            cols_ordem = ['Data', 'Cliente', 'Tipo', 'Venda Turbo', 'Valor Venda/Resgate', 'Valor Cashback']
            df_historico = df_historico.reindex(columns=cols_ordem)
            
            st.dataframe(df_historico, hide_index=True, use_container_width=True)
        else:
            st.info("Nenhum lançamento encontrado com os filtros selecionados.")
    else:
        st.info("Nenhum lançamento registrado no histórico.")

def render_home():
    """Página de boas-vindas e resumo geral."""
    st.header("Seja Bem-Vinda ao Painel de Gestão de Cashback Doce&Bella!")
    st.markdown("---")

    total_clientes = len(st.session_state.clientes)
    total_cashback_pendente = st.session_state.clientes['Cashback Disponível'].sum()
    
    # Filtra vendas
    vendas_df = st.session_state.lancamentos[st.session_state.lancamentos['Tipo'] == 'Venda']
    
    total_vendas_mes = 0.0
    
    if not vendas_df.empty:
        # Garante que a coluna 'Data' seja tratada corretamente
        vendas_df_copy = vendas_df.copy()
        vendas_df_copy['Data'] = pd.to_datetime(vendas_df_copy['Data'], errors='coerce')
        
        vendas_mes = vendas_df_copy[
            vendas_df_copy['Data'].apply(
                # Filtra pelo mês atual
                lambda x: x.month == date.today().month if pd.notna(x) else False
            )
        ]
        
        if not vendas_mes.empty:
            # Garante que a coluna de valor é numérica antes de somar
            vendas_mes['Valor Venda/Resgate'] = pd.to_numeric(vendas_mes['Valor Venda/Resgate'], errors='coerce').fillna(0)
            total_vendas_mes = vendas_mes['Valor Venda/Resgate'].sum()


    col1, col2, col3 = st.columns(3)
    
    col1.metric("Clientes Cadastrados", total_clientes)
    col2.metric("Total de Cashback Devido", f"R$ {total_cashback_pendente:,.2f}")
    col3.metric("Volume de Vendas (Mês Atual)", f"R$ {total_vendas_mes:,.2f}")

    st.markdown("---")
    st.markdown("### Próximos Passos Rápidos")
    
    col_nav1, col_nav2, col_nav3, col_nav4 = st.columns(4)
    
    if col_nav1.button("▶️ Lançar Nova Venda", use_container_width=True):
        st.session_state.pagina_atual = "Lançamento"
        st.rerun()
    
    if col_nav2.button("👥 Cadastrar Nova Cliente", use_container_width=True):
        st.session_state.pagina_atual = "Cadastro"
        st.rerun()
        
    if col_nav3.button("⚡ Produtos Turbo", use_container_width=True):
        st.session_state.pagina_atual = "Produtos Turbo"
        st.rerun()

    if col_nav4.button("📈 Ver Relatórios de Vendas", use_container_width=True):
        st.session_state.pagina_atual = "Relatórios"
        st.rerun()


# --- Mapeamento das Páginas ---
PAGINAS = {
    "Home": render_home,
    "Lançamento": render_lancamento,
    "Cadastro": render_cadastro,
    "Produtos Turbo": render_produtos_turbo,
    "Relatórios": render_relatorios
}

if "pagina_atual" not in st.session_state:
    st.session_state.pagina_atual = "Home"


# --- Renderiza o Header Customizado ---

def render_header():
    """Renderiza o header customizado com a navegação em botões."""
    
    # Colunas para o Logo e a Navegação (Aumentamos a coluna do logo)
    col_logo, col_nav = st.columns([1.5, 5])
    
    with col_logo:
        st.markdown(f'''
            <div class="logo-container">
                <img src="{LOGO_DOCEBELLA_URL}" alt="Doce&Bella Logo" style="height: 200px;">  
            </div>
        ''', unsafe_allow_html=True)
        
    with col_nav:
        # A barra rosa forte onde os botões se apoiam
        st.markdown('<div style="height: 5px; background-color: #E91E63;"></div>', unsafe_allow_html=True)  
        
        # Container de botões (Horizontal)
        cols_botoes = st.columns([1] * len(PAGINAS))
        
        paginas_ordenadas = ["Home", "Lançamento", "Cadastro", "Produtos Turbo", "Relatórios"]
        
        for i, nome in enumerate(paginas_ordenadas):
            if nome in PAGINAS:
                is_active = st.session_state.pagina_atual == nome
                
                # Usa uma classe CSS para o estado ativo
                if cols_botoes[i].button(
                    nome,  
                    key=f"nav_{nome}",  
                    use_container_width=True,  
                    help=f"Ir para {nome}"
                ):
                    st.session_state.pagina_atual = nome
                    st.rerun()
                
                # Aplica a classe CSS injetando o JavaScript/HTML após o botão ser renderizado
                if is_active:
                    st.markdown(f"""
                        <script>
                            // Tenta encontrar o último botão criado no stHorizontalBlock e aplica a classe
                            var buttons = window.parent.document.querySelectorAll('div[data-testid^="stHorizontalBlock"] button');
                            var lastButton = buttons[buttons.length - {len(PAGINAS) - i}];
                            if (lastButton) {{
                                lastButton.classList.add('active-nav-button');
                            }}
                        </script>
                    """, unsafe_allow_html=True)


# --- EXECUÇÃO PRINCIPAL ---

# 1. Inicialização de DataFrames vazios para evitar 'AttributeError'
CLIENTES_COLS_FULL = ['Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível', 'Gasto Acumulado', 'Nivel Atual', 'Indicado Por', 'Primeira Compra Feita']
LANÇAMENTOS_COLS_FULL = ['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback', 'Venda Turbo'] 
PRODUTOS_TURBO_COLS_FULL = ['Nome Produto', 'Data Início', 'Data Fim', 'Ativo'] 

if 'clientes' not in st.session_state:
    st.session_state.clientes = pd.DataFrame(columns=CLIENTES_COLS_FULL)
if 'lancamentos' not in st.session_state:
    st.session_state.lancamentos = pd.DataFrame(columns=LANÇAMENTOS_COLS_FULL)
if 'produtos_turbo' not in st.session_state:
    st.session_state.produtos_turbo = pd.DataFrame(columns=PRODUTOS_TURBO_COLS_FULL)
    
# 2. Garante que as variáveis de estado de edição e deleção existam
if 'editing_client' not in st.session_state:
    st.session_state.editing_client = False
if 'deleting_client' not in st.session_state:
    st.session_state.deleting_client = False
# Garante que o valor da venda para cálculo instantâneo esteja pronto
if 'valor_venda' not in st.session_state:
    st.session_state.valor_venda = 0.00
    
# Inicialização da chave de controle de versão
if 'data_version' not in st.session_state:
    st.session_state.data_version = 0


# 3. Carregamento: Chamamos a função carregar_dados. O cache é limpo em salvar_dados()
carregar_dados(st.session_state.data_version)

# Renderiza o cabeçalho customizado no topo da página
render_header()

# Renderização do conteúdo da página selecionada
st.markdown('<div style="padding-top: 20px;">', unsafe_allow_html=True)
PAGINAS[st.session_state.pagina_atual]()
st.markdown('</div>', unsafe_allow_html=True)
