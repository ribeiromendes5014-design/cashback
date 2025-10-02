import streamlit as st
import pandas as pd
from datetime import date
import os
import io # Necessário para ler/escrever o CSV via conexão do GitHub
import requests
from io import StringIO
import base64

# Tenta importar PyGithub para persistência.
try:
    from github import Github
except ImportError:
    # Cria uma classe dummy se PyGithub não estiver instalado (apenas para evitar crash local)
    class Github:
        def __init__(self, token): pass
        def get_repo(self, repo_name): return self
        def get_contents(self, path, ref): return type('Contents', (object,), {'sha': 'dummy_sha'})
        def update_file(self, path, msg, content, sha, branch): pass
        def create_file(self, path, msg, content, branch): pass
    st.warning("⚠️ Biblioteca 'PyGithub' não encontrada. A persistência no GitHub não funcionará. Instale: pip install PyGithub")


# --- Nomes dos arquivos CSV e Configuração ---
CLIENTES_CSV = 'clientes.csv'
LANÇAMENTOS_CSV = 'lancamentos.csv'
CASHBACK_PERCENTUAL = 0.03

# --- Configuração de Persistência (Puxa do st.secrets) ---
try:
    # CORREÇÃO: Acessa os segredos assumindo que estão na raiz do secrets.toml (formato mais comum)
    TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO_OWNER = st.secrets["REPO_OWNER"]
    REPO_NAME = st.secrets["REPO_NAME"]
    BRANCH = st.secrets.get("BRANCH", "main")
    
    # URL base para leitura (raw content)
    URL_BASE_REPOS = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/"
    PERSISTENCE_MODE = "GITHUB"
    
except KeyError:
    # Fallback para o modo LOCAL se o token não for encontrado
    st.warning("⚠️ Chaves 'GITHUB_TOKEN', 'REPO_OWNER' ou 'REPO_NAME' faltando em secrets.toml. Usando Modo Local.")
    PERSISTENCE_MODE = "LOCAL"

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
    except Exception as e:
        # print(f"Erro ao carregar {url}: {e}")
        return None

def salvar_dados_no_github(df: pd.DataFrame, file_path: str, commit_message: str):
    """
    Salva o DataFrame CSV no GitHub usando a API (PyGithub).
    """
    if PERSISTENCE_MODE != "GITHUB":
        # Não tenta salvar se não estiver no modo GitHub
        return False
    
    df_temp = df.copy()
    
    # 1. Prepara DataFrame: Garante que as datas sejam strings
    if 'Data' in df_temp.columns:
        df_temp['Data'] = pd.to_datetime(df_temp['Data'], errors='coerce').apply(
            lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
        )

    try:
        g = Github(TOKEN)
        repo = g.get_repo(f"{REPO_OWNER}/{REPO_NAME}")
        csv_string = df_temp.to_csv(index=False, encoding="utf-8-sig")

        try:
            # Tenta obter o SHA do conteúdo atual (necessário para update)
            contents = repo.get_contents(file_path, ref=BRANCH)
            # Atualiza o arquivo
            repo.update_file(contents.path, commit_message, csv_string, contents.sha, branch=BRANCH)
            st.success(f"📁 Arquivo '{file_path}' salvo (atualizado) no GitHub!")
        except Exception:
            # Cria o arquivo (se não existir)
            repo.create_file(file_path, commit_message, csv_string, branch=BRANCH)
            st.success(f"📁 Arquivo '{file_path}' salvo (criado) no GitHub!")

        return True

    except Exception as e:
        st.error(f"❌ ERRO CRÍTICO ao salvar no GitHub ({file_path}): {e}")
        st.error("Verifique se seu TOKEN tem permissões de 'repo' e se o repositório existe.")
        return False

# --- Funções de Carregamento/Salvamento (Suporte a GitHub e Local) ---

# Função salva-dados movida para cima para ser acessível na carregar_dados
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
    df = pd.DataFrame(columns=df_columns) # DF vazio padrão
    
    if PERSISTENCE_MODE == "GITHUB":
        url_raw = f"{URL_BASE_REPOS}{file_path}"
        df_carregado = load_csv_github(url_raw)
        if df_carregado is not None:
            df = df_carregado
        
    elif os.path.exists(file_path): # Modo Local
        try: 
            df = pd.read_csv(file_path)
        except pd.errors.EmptyDataError:
            pass
            
    # Garante as colunas e tratamento de tipos
    for col in df_columns:
        if col not in df.columns: df[col] = "" 
        
    return df[df_columns]

def carregar_dados():
    """Tenta carregar os DataFrames, priorizando o GitHub se configurado."""
    
    # Carrega Clientes
    st.session_state.clientes = carregar_dados_do_csv(
        CLIENTES_CSV, ['Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível']
    )
    
    # Carrega Lançamentos
    st.session_state.lancamentos = carregar_dados_do_csv(
        LANÇAMENTOS_CSV, ['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback']
    )
    
    # Inicialização Pós-Carga: Adiciona cliente exemplo se vazio e garante tipos
    if st.session_state.clientes.empty:
        st.session_state.clientes.loc[0] = ['Cliente Exemplo', 'Primeiro Cliente', '99999-9999', 50.00]
        # Salva o cliente de exemplo (necessário para inicializar o CSV no GitHub)
        # ESTE PONTO AGORA CHAMA salvar_dados, que está definido acima
        salvar_dados() 
        
    st.session_state.clientes['Cashback Disponível'] = pd.to_numeric(st.session_state.clientes['Cashback Disponível'], errors='coerce').fillna(0.0)

    if not st.session_state.lancamentos.empty:
        # Garante que a coluna 'Data' seja do tipo date para os filtros
        st.session_state.lancamentos['Data'] = pd.to_datetime(st.session_state.lancamentos['Data'], errors='coerce').dt.date
    

# --- Funções de Edição e Exclusão (Chamam salvar_dados()) ---

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


# --- Inicializa o Streamlit e carrega os dados ---
st.set_page_config(layout="wide", page_title="Sistema de Cashback")

# Verifica e informa o modo de persistência
if PERSISTENCE_MODE == "GITHUB":
    st.sidebar.success("💾 Persistência: GitHub API Ativa (Commits automáticos)")
    st.sidebar.caption(f"Repo: {REPO_OWNER}/{REPO_NAME} | Branch: {BRANCH}")
else:
    st.sidebar.warning("⚠️ Persistência: Modo Local. Alterações não serão salvas após o reinício do app.")

if 'clientes' not in st.session_state:
    carregar_dados()
if 'editing_client' not in st.session_state:
    st.session_state.editing_client = False
if 'deleting_client' not in st.session_state:
    st.session_state.deleting_client = False


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
    
    # 1. Validações
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
        
    # 2. Processa o resgate
    st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'] -= valor_resgate
    
    # 3. Registra o lançamento
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

# --- Abas do Aplicativo ---

tab1, tab2, tab3 = st.tabs(["Lançamento (Venda/Resgate)", "Cadastro de Clientes", "Relatórios"])

# --------------------------
# --- ABA 1: Lançamento ---
# --------------------------
with tab1:
    st.header("Lançamento de Venda e Resgate de Cashback")
    st.markdown("---")
    
    # Opção para Lançar Venda ou Resgatar
    operacao = st.radio("Selecione a Operação:", ["Lançar Nova Venda", "Resgatar Cashback"], key='op_selecionada')

    if operacao == "Lançar Nova Venda":
        st.subheader("Nova Venda (Cashback de 3%)")
        
        with st.form("form_venda", clear_on_submit=True):
            clientes_nomes = [''] + st.session_state.clientes['Nome'].tolist()
            cliente_selecionado = st.selectbox(
                "Nome da Cliente (Selecione ou digite para buscar):", 
                options=clientes_nomes, 
                index=0,
                key='nome_cliente_venda'
            )
            
            valor_venda = st.number_input("Valor da Venda (R$):", min_value=0.01, step=50.0, format="%.2f", key='valor_venda')
            
            # Cálculo automático de Cashback (3%)
            cashback_calculado = valor_venda * CASHBACK_PERCENTUAL
            st.metric(label="Cashback a Gerar (3%):", value=f"R$ {cashback_calculado:.2f}")
            
            data_venda = st.date_input("Data da Venda:", value=date.today(), key='data_venda')
            
            submitted_venda = st.form_submit_button("Lançar Venda e Gerar Cashback")
            
            if submitted_venda:
                if cliente_selecionado == '':
                    st.error("Por favor, selecione ou digite o nome de uma cliente.")
                elif cliente_selecionado not in st.session_state.clientes['Nome'].values:
                    st.warning("Cliente não encontrado. Por favor, cadastre-o primeiro na aba 'Cadastro de Clientes'.")
                else:
                    lancar_venda(cliente_selecionado, valor_venda, cashback_calculado, data_venda)

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
                    # Puxa o saldo atual do cliente selecionado (garante que seja o saldo mais recente)
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
                    # Se o cliente for selecionado, o saldo_atual será puxado corretamente antes da validação.
                    resgatar_cashback(cliente_resgate, valor_resgate, valor_venda_resgate, data_resgate, saldo_atual)

# --------------------------
# --- ABA 2: Cadastro ---
# --------------------------
with tab2:
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


# --------------------------
# --- ABA 3: Relatórios ---
# --------------------------
with tab3:
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
        # Filtro por Data
        if data_selecionada:
            df_historico['Data'] = df_historico['Data'].astype(str)
            data_selecionada_str = str(data_selecionada)
            df_historico = df_historico[df_historico['Data'] == data_selecionada_str]

        # Filtro por Tipo
        if tipo_selecionado != 'Todos':
            df_historico = df_historico[df_historico['Tipo'] == tipo_selecionado]

        # Formata a coluna Valor Venda/Resgate e Valor Cashback
        if not df_historico.empty:
            df_historico['Valor Venda/Resgate'] = df_historico['Valor Venda/Resgate'].map('R$ {:.2f}'.format)
            df_historico['Valor Cashback'] = df_historico['Valor Cashback'].map('R$ {:.2f}'.format)
            st.dataframe(df_historico, hide_index=True, use_container_width=True)
        else:
            st.info("Nenhum lançamento encontrado com os filtros selecionados.")
    else:
        st.info("Nenhum lançamento registrado no histórico.")
