import streamlit as st
import pandas as pd
from datetime import date
import os

# --- Nomes dos arquivos CSV ---
CLIENTES_CSV = 'clientes.csv'
LANÇAMENTOS_CSV = 'lancamentos.csv'
CASHBACK_PERCENTUAL = 0.03

# --- Funções de Carregamento e Salvamento de Dados ---

def carregar_dados():
    """Tenta carregar os DataFrames a partir dos CSVs. Se não existirem, cria DataFrames vazios."""
    
    # Carregar Clientes
    if os.path.exists(CLIENTES_CSV):
        st.session_state.clientes = pd.read_csv(CLIENTES_CSV)
    else:
        st.session_state.clientes = pd.DataFrame(columns=['Nome', 'Apelido/Descrição', 'Telefone', 'Cashback Disponível'])
        # Adiciona um cliente de exemplo se estiver vazio
        if st.session_state.clientes.empty:
            st.session_state.clientes.loc[0] = ['Cliente Exemplo', 'Primeiro Cliente', '99999-9999', 50.00]
            salvar_dados() # Salva o cliente de exemplo
            
    # Carregar Lançamentos
    if os.path.exists(LANÇAMENTOS_CSV):
        st.session_state.lancamentos = pd.read_csv(LANÇAMENTOS_CSV)
        # Garante que a coluna 'Data' seja do tipo date
        st.session_state.lancamentos['Data'] = pd.to_datetime(st.session_state.lancamentos['Data']).dt.date
    else:
        st.session_state.lancamentos = pd.DataFrame(columns=['Data', 'Cliente', 'Tipo', 'Valor Venda/Resgate', 'Valor Cashback'])

def salvar_dados():
    """Salva os DataFrames de volta nos arquivos CSV."""
    st.session_state.clientes.to_csv(CLIENTES_CSV, index=False)
    st.session_state.lancamentos.to_csv(LANÇAMENTOS_CSV, index=False)

# --- Inicializa o Session State carregando do CSV ---
if 'clientes' not in st.session_state:
    carregar_dados()

# --- Funções de manipulação de dados atualizadas com a função salvar_dados() ---

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
    salvar_dados() # <-- Salva o CSV após o cadastro
    st.success(f"Cliente '{nome}' cadastrado com sucesso!")
    return True

def lancar_venda(cliente_nome, valor_venda, valor_cashback, data_venda):
    """Lança uma venda, atualiza o cashback do cliente e salva o CSV."""
    # 1. Atualiza o saldo de cashback do cliente
    st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'] += valor_cashback
    
    # 2. Registra o lançamento
    novo_lancamento = pd.DataFrame({
        'Data': [data_venda],
        'Cliente': [cliente_nome],
        'Tipo': ['Venda'],
        'Valor Venda/Resgate': [valor_venda],
        'Valor Cashback': [valor_cashback]
    })
    st.session_state.lancamentos = pd.concat([st.session_state.lancamentos, novo_lancamento], ignore_index=True)
    
    salvar_dados() # <-- Salva os CSVs após o lançamento
    st.success(f"Venda de R$ {valor_venda:.2f} lançada para {cliente_nome}. Cashback de R$ {valor_cashback:.2f} adicionado.")

def resgatar_cashback(cliente_nome, valor_resgate, valor_venda_atual, data_resgate):
    """Processa o resgate de cashback e salva o CSV."""
    saldo_disponivel = st.session_state.clientes.loc[st.session_state.clientes['Nome'] == cliente_nome, 'Cashback Disponível'].iloc[0]
    
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
    
    salvar_dados() # <-- Salva os CSVs após o resgate
    st.success(f"Resgate de R$ {valor_resgate:.2f} realizado com sucesso para {cliente_resgate}.")

# --- O RESTANTE DO CÓDIGO (ABA 1, 2, 3) PERMANECE O MESMO ---

# Se você já tem a parte de UI (Interface do Usuário) do código anterior, 
# apenas substitua as funções e o bloco de inicialização acima.

# Exemplo de como começa a UI:
tab1, tab2, tab3 = st.tabs(["Lançamento (Venda/Resgate)", "Cadastro de Clientes", "Relatórios"])

# ... (todo o código das abas 1, 2 e 3 do projeto original) ...

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
                else:
                    if cliente_selecionado not in st.session_state.clientes['Nome'].values:
                        st.warning("Cliente não encontrado. Por favor, cadastre-o primeiro na aba 'Cadastro de Clientes'.")
                    else:
                        lancar_venda(cliente_selecionado, valor_venda, cashback_calculado, data_venda)

    elif operacao == "Resgatar Cashback":
        st.subheader("Resgate de Cashback")
        
        # Filtra clientes com saldo positivo para resgate
        clientes_com_cashback = st.session_state.clientes[st.session_state.clientes['Cashback Disponível'] >= 20.00]
        clientes_options = [''] + clientes_com_cashback['Nome'].tolist()
        
        with st.form("form_resgate", clear_on_submit=True):
            cliente_resgate = st.selectbox(
                "Cliente para Resgate:", 
                options=clientes_options,
                index=0,
                key='nome_cliente_resgate'
            )
            
            # Se um cliente foi selecionado, mostra o saldo e a venda atual para validação
            if cliente_resgate != '':
                saldo_atual = clientes_com_cashback.loc[clientes_com_cashback['Nome'] == cliente_resgate, 'Cashback Disponível'].iloc[0]
                st.info(f"Saldo Disponível para {cliente_resgate}: R$ {saldo_atual:.2f}")
                
                valor_venda_resgate = st.number_input(
                    "Valor da Venda Atual (para cálculo do limite de 50%):", 
                    min_value=0.01, 
                    step=50.0, 
                    format="%.2f", 
                    key='valor_venda_resgate'
                )
                
                max_resgate_disp = valor_venda_resgate * 0.50
                st.warning(f"Resgate Máximo Permitido (50% da venda): R$ {max_resgate_disp:.2f}")

                valor_resgate = st.number_input(
                    "Valor do Resgate (Mínimo R$20,00):", 
                    min_value=0.00, 
                    step=1.00, 
                    format="%.2f", 
                    key='valor_resgate'
                )
                
                data_resgate = st.date_input("Data do Resgate:", value=date.today(), key='data_resgate')

                submitted_resgate = st.form_submit_button("Confirmar Resgate")
                
                if submitted_resgate:
                    if valor_resgate > 0:
                        resgatar_cashback(cliente_resgate, valor_resgate, valor_venda_resgate, data_resgate)
                    else:
                        st.error("O valor do resgate deve ser maior que zero.")
            else:
                st.warning("Selecione um cliente com cashback disponível para resgate.")
                
# --------------------------
# --- ABA 2: Cadastro ---
# --------------------------
with tab2:
    st.header("Cadastro de Clientes")
    st.markdown("---")
    
    with st.form("form_cadastro_cliente", clear_on_submit=True):
        st.subheader("Novo Cliente")
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
    st.subheader("Clientes Cadastrados")
    # Exibe a tabela de clientes
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
    ranking_cashback.index += 1 # Começa a indexar em 1
    st.dataframe(ranking_cashback[['Nome', 'Cashback Disponível']], use_container_width=True)
    st.markdown("---")


    # --- Ranking de Maior Volume de Compras ---
    st.subheader("💰 Ranking: Maior Volume de Compras (Vendas)")
    
    # Filtra apenas as vendas e agrupa
    vendas_df = st.session_state.lancamentos[st.session_state.lancamentos['Tipo'] == 'Venda']
    ranking_compras = vendas_df.groupby('Cliente')['Valor Venda/Resgate'].sum().reset_index()
    ranking_compras.columns = ['Cliente', 'Total Compras (R$)']
    ranking_compras = ranking_compras.sort_values(by='Total Compras (R$)', ascending=False).reset_index(drop=True)
    ranking_compras['Total Compras (R$)'] = ranking_compras['Total Compras (R$)'].map('{:.2f}'.format)
    ranking_compras.index += 1
    st.dataframe(ranking_compras, hide_index=False, use_container_width=True)
    st.markdown("---")
    
    # --- Histórico de Lançamentos ---
    st.subheader("📄 Histórico de Lançamentos")
    
    col_data, col_tipo = st.columns(2)
    with col_data:
        data_selecionada = st.date_input("Filtrar por Data:", value=None)
    with col_tipo:
        tipo_selecionado = st.selectbox("Filtrar por Tipo:", ['Todos', 'Venda', 'Resgate'], index=0)

    df_historico = st.session_state.lancamentos.copy()
    
    # Filtro por Data
    if data_selecionada and not df_historico.empty:
        # Garante que a coluna 'Data' seja str/objeto para a comparação
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