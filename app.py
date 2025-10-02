# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import date
import requests
from io import StringIO
import io, os
import base64

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
CASHBACK_PERCENTUAL = 0.03 # 3% do valor da venda

# Configuração do logo para o novo layout
LOGO_DOCEBELLA_URL = "https://i.ibb.co/fYCWBKTm/Logo-Doce-Bella-Cosm-tico.png" # Link do logo

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
    
    if 'Data' in df_temp.columns:
        df_temp['Data'] = pd.to_datetime(df_temp['Data'], errors='coerce').apply(
            lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
        )

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
    """Salva os DataFrames de volta nos arquivos CSV, priorizando o GitHub."""
    if PERSISTENCE_MODE == "GITHUB":
        salvar_dados_no_github(st.session_state.clientes, CLIENTES_CSV, "AUTOSAVE: Atualizando clientes e saldos.")
        salvar_dados_no_github(st.session_state.lancamentos, LANÇAMENTOS_CSV, "AUTOSAVE: Atualizando histórico de lançamentos.")
    else: # Modo LOCAL
        st.session_state.clientes.to_csv(CLIENTES_CSV, index=False)
        st.session_state.lancamentos.to_csv(LANÇAMENTOS_CSV, index=False)
        
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
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            pass
            
    for col in df_columns:
        if col not in df.columns: df[col] = "" 
        
    return df[df_columns]

@st.cache_data(show_spinner="Carregando dados...")
def carregar_dados():
    """Tenta carregar os DataFrames, priorizando o GitHub se configurado."""
    
    st.session_state.clientes = carregar_dados_do_csv(
        CLIENTES_CSV, ['Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível']
    )
    
    st.session_state.lancamentos = carregar_dados_do_csv(
        LANÇAMENTOS_CSV, ['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback']
    )
    
    # Adiciona a inicialização de DF vazio para evitar erro no primeiro acesso
    if 'clientes' not in st.session_state:
        st.session_state.clientes = pd.DataFrame(columns=['Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível'])
    if 'lancamentos' not in st.session_state:
        st.session_state.lancamentos = pd.DataFrame(columns=['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback'])


    if st.session_state.clientes.empty:
        st.session_state.clientes.loc[0] = ['Cliente Exemplo', 'Primeiro Cliente', '99999-9999', 50.00]
        salvar_dados() 
        
    st.session_state.clientes['Cashback Disponível'] = pd.to_numeric(st.session_state.clientes['Cashback Disponível'], errors='coerce').fillna(0.0)

    if not st.session_state.lancamentos.empty:
        st.session_state.lancamentos['Data'] = pd.to_datetime(st.session_state.lancamentos['Data'], errors='coerce').dt.date
    

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
    """Exclui o cliente e todas as suas transações, depois salva."""
    
    st.session_state.clientes = st.session_state.clientes[
        st.session_state.clientes['Nome'] != nome_cliente
    ].reset_index(drop=True)
    
    st.session_state.lancamentos = st.session_state.lancamentos[
        st.session_state.lancamentos['Cliente'] != nome_cliente
    ].reset_index(drop=True)
    
    salvar_dados()
    st.session_state.deleting_client = False
    st.success(f"Cliente '{nome_cliente}' e todos os seus lançamentos foram excluídos.")
    st.rerun()


def cadastrar_cliente(nome, apelido, telefone):
    """Adiciona um novo cliente ao DataFrame de clientes e salva o CSV."""
    if nome in st.session_state.clientes['Nome'].values:
        st.error("Erro: Já existe um cliente com este nome.")
        return False
        
    novo_cliente = pd.DataFrame({
        'Nome': [nome],
        'Apelido/Descrição': [apelido],
        'Telefone': [telefone],
        'Cashback Disponível': [0.00]
    })
    st.session_state.clientes = pd.concat([st.session_state.clientes, novo_cliente], ignore_index=True)
    salvar_dados() 
    st.success(f"Cliente '{nome}' cadastrado com sucesso!")
    st.rerun()

def lancar_venda(cliente_nome, valor_venda, valor_cashback, data_venda):
    """Lança uma venda, atualiza o cashback do cliente e salva o CSV."""
    st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'] += valor_cashback
    
    novo_lancamento = pd.DataFrame({
        'Data': [data_venda],
        'Cliente': [cliente_nome],
        'Tipo': ['Venda'],
        'Valor Venda/Resgate': [valor_venda],
        'Valor Cashback': [valor_cashback]
    })
    st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, novo_lancamento], ignore_index=True)
    
    salvar_dados() 
    st.success(f"Venda de R$ {valor_venda:.2f} lançada para {cliente_nome}. Cashback de R$ {valor_cashback:.2f} adicionado.")

def resgatar_cashback(cliente_nome, valor_resgate, valor_venda_atual, data_resgate, saldo_disponivel):
    """Processa o resgate de cashback."""
    
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
    
    novo_lancamento = pd.DataFrame({
        'Data': [data_resgate],
        'Cliente': [cliente_nome],
        'Tipo': ['Resgate'],
        'Valor Venda/Resgate': [valor_venda_atual],
        'Valor Cashback': [-valor_resgate]  
    })
    st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, novo_lancamento], ignore_index=True)
    
    salvar_dados() 
    st.success(f"Resgate de R$ {valor_resgate:.2f} realizado com sucesso para {cliente_nome}.")


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

    </style>
""", unsafe_allow_html=True)

# --- Definição das Páginas (Funções de renderização) ---

def render_lancamento():
    """Renderiza a página de Lançamento (Venda/Resgate) - Antiga Tab 1"""
    
    st.header("Lançamento de Venda e Resgate de Cashback")
    st.markdown("---")
    
    operacao = st.radio("Selecione a Operação:", ["Lançar Nova Venda", "Resgatar Cashback"], key='op_selecionada')

    # (CÓDIGO DA ABA 1 - Lançamento)
    if operacao == "Lançar Nova Venda":
        st.subheader("Nova Venda (Cashback de 3%)")
        
        # 1. MOVIDO PARA FORA DO FORM: Valor da Venda (para cálculo em tempo real)
        # O widget number_input fora do form atualiza a session_state a cada interação, 
        # forçando o rerun e o recálculo do cashback.
        valor_venda = st.number_input("Valor da Venda (R$):", min_value=0.00, step=50.0, format="%.2f", key='valor_venda')
        
        # Inicializa o estado se for o primeiro acesso
        if 'valor_venda' not in st.session_state:
            st.session_state.valor_venda = 0.00
            
        # 2. CÁLCULO INSTANTÂNEO
        cashback_calculado = st.session_state.valor_venda * CASHBACK_PERCENTUAL
        
        # 3. EXIBIÇÃO INSTANTÂNEA
        st.metric(label=f"Cashback a Gerar ({int(CASHBACK_PERCENTUAL * 100)}%):", value=f"R$ {cashback_calculado:.2f}")
        
        with st.form("form_venda", clear_on_submit=True):
            clientes_nomes = [''] + st.session_state.clientes['Nome'].tolist()
            cliente_selecionado = st.selectbox(
                "Nome da Cliente (Selecione ou digite para buscar):", 
                options=clientes_nomes, 
                index=0,
                key='nome_cliente_venda'
            )
            
            st.caption(f"Valor da Venda a ser lançado: **R$ {st.session_state.valor_venda:.2f}**")
            
            data_venda = st.date_input("Data da Venda:", value=date.today(), key='data_venda')
            
            submitted_venda = st.form_submit_button("Lançar Venda e Gerar Cashback")
            
            if submitted_venda:
                # Usa os valores recalculados no momento da submissão
                lancamento_valor_venda = st.session_state.valor_venda
                lancamento_cashback = lancamento_valor_venda * CASHBACK_PERCENTUAL
                
                if cliente_selecionado == '':
                    st.error("Por favor, selecione ou digite o nome de uma cliente.")
                elif lancamento_valor_venda <= 0.00:
                    st.error("O valor da venda deve ser maior que R$ 0,00.")
                elif cliente_selecionado not in st.session_state.clientes['Nome'].values:
                    st.warning("Cliente não encontrado. Por favor, cadastre-o primeiro na seção 'Cadastro'.")
                else:
                    lancar_venda(cliente_selecionado, lancamento_valor_venda, lancamento_cashback, data_venda)

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


def render_cadastro():
    """Renderiza a página de Cadastro e Gestão de Clientes - Antiga Tab 2"""
    
    st.header("Cadastro de Clientes e Gestão")
    
    # ------------------
    # --- NOVO CADASTRO ---
    # ------------------
    st.subheader("Novo Cliente")
    with st.form("form_cadastro_cliente", clear_on_submit=True):
        nome = st.text_input("Nome da Cliente (Obrigatório):", key='cadastro_nome')
        apelido = st.text_input("Apelido ou Descrição (Opcional):", key='cadastro_apelido')
        telefone = st.text_input("Número de Telefone:", help="Ex: 99999-9999", key='cadastro_telefone')
        
        submitted_cadastro = st.form_submit_button("Cadastrar Cliente")
        
        if submitted_cadastro:
            if nome:
                cadastrar_cliente(nome.strip(), apelido.strip(), telefone.strip())
            else:
                st.error("O campo 'Nome da Cliente' é obrigatório.")

    st.markdown("---")
    
    # --------------------------------
    # --- EDIÇÃO E EXCLUSÃO (NOVO) ---
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
    st.subheader("Clientes Cadastrados (Visualização)")
    st.dataframe(st.session_state.clientes, hide_index=True, use_container_width=True)


def render_relatorios():
    """Renderiza a página de Relatórios e Rankings - Antiga Tab 3"""
    
    st.header("Relatórios e Rankings")
    st.markdown("---")

    # --- Ranking de Cashback ---
    st.subheader("🏆 Ranking: Maior Saldo de Cashback")
    ranking_cashback = st.session_state.clientes.sort_values(by='Cashback Disponível', ascending=False).reset_index(drop=True)
    ranking_cashback.index += 1 
    st.dataframe(ranking_cashback[['Nome', 'Cashback Disponível']], use_container_width=True)
    st.markdown("---")


    # --- Ranking de Maior Volume de Compras ---
    st.subheader("💰 Ranking: Maior Volume de Compras (Vendas)")
    
    vendas_df = st.session_state.lancamentos[st.session_state.lancamentos['Tipo'] == 'Venda'].copy()
    if not vendas_df.empty:
        vendas_df['Valor Venda/Resgate'] = pd.to_numeric(vendas_df['Valor Venda/Resgate'], errors='coerce').fillna(0)
        ranking_compras = vendas_df.groupby('Cliente')['Valor Venda/Resgate'].sum().reset_index()
        ranking_compras.columns = ['Cliente', 'Total Compras (R$)']
        ranking_compras = ranking_compras.sort_values(by='Total Compras (R$)', ascending=False).reset_index(drop=True)
        ranking_compras['Total Compras (R$)'] = ranking_compras['Total Compras (R$)'].map('R$ {:.2f}'.format)
        ranking_compras.index += 1
        st.dataframe(ranking_compras, hide_index=False, use_container_width=True)
    else:
        st.info("Nenhuma venda registrada ainda para calcular o ranking de compras.")
    st.markdown("---")
    
    # --- Histórico de Lançamentos ---
    st.subheader("📄 Histórico de Lançamentos")
    
    col_data, col_tipo = st.columns(2)
    with col_data:
        data_selecionada = st.date_input("Filtrar por Data:", value=None)
    with col_tipo:
        tipo_selecionado = st.selectbox("Filtrar por Tipo:", ['Todos', 'Venda', 'Resgate'], index=0)

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
    
    col_nav1, col_nav2, col_nav3 = st.columns(3)
    
    if col_nav1.button("▶️ Lançar Nova Venda", use_container_width=True):
        st.session_state.pagina_atual = "Lançamento"
        st.rerun()
    
    if col_nav2.button("👥 Cadastrar Nova Cliente", use_container_width=True):
        st.session_state.pagina_atual = "Cadastro"
        st.rerun()

    if col_nav3.button("📈 Ver Relatórios de Vendas", use_container_width=True):
        st.session_state.pagina_atual = "Relatórios"
        st.rerun()


# --- Mapeamento das Páginas ---
PAGINAS = {
    "Home": render_home,
    "Lançamento": render_lancamento,
    "Cadastro": render_cadastro,
    "Relatórios": render_relatorios
}

if "pagina_atual" not in st.session_state:
    st.session_state.pagina_atual = "Home"


# --- Renderiza o Header Customizado ---

def render_header():
    """Renderiza o header customizado com a navegação em botões."""
    
    # Colunas para o Logo e a Navegação (Aumentamos a coluna do logo)
    col_logo, col_nav = st.columns([1.5, 4])
    
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
        
        paginas_ordenadas = ["Home", "Lançamento", "Cadastro", "Relatórios"]
        
        for i, nome in enumerate(paginas_ordenadas):
            if nome in PAGINAS:
                is_active = st.session_state.pagina_atual == nome
                
                # Usa uma classe CSS para o estado ativo
                button_class = "active-nav-button" if is_active else ""
                
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
                            var button = window.parent.document.querySelector('button[kind="secondary"][data-testid^="stHorizontalBlock"]');
                            if (button) {{
                                button.classList.add('active-nav-button');
                            }}
                        </script>
                    """, unsafe_allow_html=True)


# --- EXECUÇÃO PRINCIPAL ---

# 1. Inicialização de DataFrames vazios para evitar 'AttributeError'
if 'clientes' not in st.session_state:
    st.session_state.clientes = pd.DataFrame(columns=['Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível'])
if 'lancamentos' not in st.session_state:
    st.session_state.lancamentos = pd.DataFrame(columns=['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback'])
    
# 2. Garante que as variáveis de estado de edição e deleção existam
if 'editing_client' not in st.session_state:
    st.session_state.editing_client = False
if 'deleting_client' not in st.session_state:
    st.session_state.deleting_client = False
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
# Garante que o valor da venda para cálculo instantâneo esteja pronto
if 'valor_venda' not in st.session_state:
    st.session_state.valor_venda = 0.00


# 3. Carregamento: Só chama carregar_dados() se os dados ainda não foram carregados na sessão.
if not st.session_state.data_loaded:
    carregar_dados()
    st.session_state.data_loaded = True

# Renderiza o cabeçalho customizado no topo da página
render_header()

# Renderização do conteúdo da página selecionada
st.markdown('<div style="padding-top: 20px;">', unsafe_allow_html=True)
PAGINAS[st.session_state.pagina_atual]()
st.markdown('</div>', unsafe_allow_html=True)
