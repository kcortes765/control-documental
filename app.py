import os
import json
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from gspread.utils import rowcol_to_a1
import pandas as pd

# ---------------------------
# Configuración Global
# ---------------------------
# Ya no usaremos el archivo local, sino que leeremos las credenciales desde la variable de entorno.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def load_credentials():
    google_creds = os.getenv("GOOGLE_CREDENTIALS")
    if google_creds:
        creds_info = json.loads(google_creds)
        return Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    else:
        raise Exception("No se encontró la variable de entorno GOOGLE_CREDENTIALS")

# URLs de los spreadsheets
URL_LOG = "https://docs.google.com/spreadsheets/d/1mMQMXNsiZOXNVVtjzI7ERZPd6sjGhvfIDPU1i5eKm-c/edit?gid=1371253785"  # LOG Documentos y planos_Rev. B
URL_LISTADO_PERSONAL = "https://docs.google.com/spreadsheets/d/1ndFNkOAGysRB-aTI930Rs31yjDy_2GnUpSNO9CEKt5Y/edit?gid=1937104554"  # Listado de Personal
URL_DOC_ENTREGADOS = "https://docs.google.com/spreadsheets/d/1w0OfsVR00UbBiNALVLbjEvc7wD_tpvj3BUBduTU8cnA/edit?gid=366220896"  # DOC. ENTREGADOS

CONTRATO = "ALIMENTACIÓN Y PREPARACIÓN CENIZA DE SODA PREPARE N° 4 Y N° 5"
ENTREGADO_POR = "MARÍA REYES"

# ---------------------------
# Funciones Básicas (sin cambios importantes)
# ---------------------------
def connect_spreadsheets(credentials):
    gc = gspread.authorize(credentials)
    sheet_log = gc.open_by_url(URL_LOG)
    sheet_listado = gc.open_by_url(URL_LISTADO_PERSONAL)
    sheet_doc_entregados = gc.open_by_url(URL_DOC_ENTREGADOS)
    return sheet_log, sheet_listado, sheet_doc_entregados

def get_trabajadores_data(sheet_listado):
    ws = sheet_listado.worksheet("Listado de Personal")
    all_values = ws.get_all_values()
    if len(all_values) < 6:
        st.error("No se encontraron suficientes filas en el Listado de Personal.")
        return {}, [], []
    header = [col.replace("\n", " ").strip().upper() for col in all_values[5]]
    records = [dict(zip(header, [cell.strip() for cell in row]))
               for row in all_values[6:] if any(cell.strip() for cell in row)]
    trabajadores_by_id = {r.get("CC CORRELATIVO ASIGNADO", "").strip(): r for r in records}
    trabajadores_names = [r.get("RESPONSABLE", "").strip() for r in records]
    return trabajadores_by_id, trabajadores_names, records

def lookup_plano_data(sheet_log, codigo_plano):
    ws = sheet_log.worksheet("LOG")
    all_values = ws.get_all_values()
    if len(all_values) < 16:
        st.error("No se encontraron suficientes filas en la hoja LOG.")
        return {}
    header = [col.strip() for col in all_values[15]]
    data_rows = all_values[16:]
    header_map = {col: idx for idx, col in enumerate(header)}
    if "N° ENTREGABLE SQM" not in header_map:
        st.error("Falta la columna 'N° ENTREGABLE SQM'.")
        return {}
    idx_search = header_map["N° ENTREGABLE SQM"]
    for row in data_rows:
        if len(row) > idx_search and str(row[idx_search]).strip().lower() == str(codigo_plano).strip().lower():
            eco = row[3] if len(row) > 3 else ""
            tipo_doc = row[5] if len(row) > 5 else ""
            desc = row[header_map.get("DESCRIPCIÓN DEL DOCUMENTO", 0)] if "DESCRIPCIÓN DEL DOCUMENTO" in header_map else ""
            disc = row[header_map.get("DISCIPLINA", 0)] if "DISCIPLINA" in header_map else ""
            rev = ""
            for col in ["REV.", "REV"]:
                if col in header_map:
                    i_rev = header_map[col]
                    if len(row) > i_rev and row[i_rev].strip():
                        rev = row[i_rev].strip()
                        break
            return {"eco": eco, "tipo_doc": tipo_doc, "descripcion": desc, "disciplina": disc, "rev": rev}
    return {}

def find_last_row(ws, start_row=29):
    all_values = ws.get_all_values()
    last_row = None
    for i in range(start_row-1, len(all_values)):
        if len(all_values[i]) > 1 and all_values[i][1].strip():
            last_row = i + 1
    return last_row

def get_item_and_next_row(ws, start_row=29):
    last_row = find_last_row(ws, start_row)
    if not last_row:
        return 1, start_row
    row_data = ws.get_all_values()[last_row - 1]
    try:
        val = int(row_data[1].strip()) if len(row_data) > 1 else 0
    except:
        val = 0
    return val + 1, last_row + 1

def update_row(ws, row_index, data, start_col=1):
    end_col = start_col + len(data) - 1
    cell_range = f"{rowcol_to_a1(row_index, start_col)}:{rowcol_to_a1(row_index, end_col)}"
    ws.update(cell_range, [data], value_input_option="USER_ENTERED")

def copy_format(ws, source_row, dest_row, start_col=1, end_col=17):
    sheet_id = ws.spreadsheet.worksheet(ws.title)._properties.get("sheetId")
    request = {
        "copyPaste": {
            "source": {
                "sheetId": sheet_id,
                "startRowIndex": source_row - 1,
                "endRowIndex": source_row,
                "startColumnIndex": start_col - 1,
                "endColumnIndex": end_col
            },
            "destination": {
                "sheetId": sheet_id,
                "startRowIndex": dest_row - 1,
                "endRowIndex": dest_row,
                "startColumnIndex": start_col - 1,
                "endColumnIndex": end_col
            },
            "pasteType": "PASTE_FORMAT",
            "pasteOrientation": "NORMAL"
        }
    }
    ws.spreadsheet.batch_update({"requests": [request]})

def parse_multi_input(user_input):
    items = []
    for line in user_input.split('\n'):
        for part in line.split(','):
            val = part.strip()
            if val:
                items.append(val)
    return list(dict.fromkeys(items))

# ---------------------------
# Interfaz de Usuario
# ---------------------------
def main():
    st.set_page_config(page_title="Ingreso de Documentos", layout="centered")
    st.title("Ingreso Masivo de Documentos")

    # Usar session_state para almacenar los códigos agregados
    if "documento_codes" not in st.session_state:
        st.session_state["documento_codes"] = []

    try:
        creds = load_credentials()
        sheet_log, sheet_listado, sheet_doc_entregados = connect_spreadsheets(creds)
        ws_doc_entregados = sheet_doc_entregados.worksheet("DOC. ENTREGADOS")
    except Exception as e:
        st.error(f"Error conectando con las hojas: {e}")
        return

    # Cargar datos de trabajadores
    try:
        trabajadores_by_id, trabajadores_names, trabajadores_data = get_trabajadores_data(sheet_listado)
    except Exception as e:
        st.error(f"Error obteniendo datos de trabajadores: {e}")
        return

    st.header("Seleccionar Trabajador")
    modo_busqueda = st.radio("Buscar por:", ["CC CORRELATIVO ASIGNADO", "Nombre"], index=0)
    trabajador = None
    if modo_busqueda == "CC CORRELATIVO ASIGNADO":
        cc_input = st.text_input("Ingresa el CC:")
        if cc_input:
            cc = cc_input.strip()
            if cc in trabajadores_by_id:
                trabajador = trabajadores_by_id[cc]
                st.success("Trabajador encontrado.")
                st.text_input("CC", value=cc, disabled=True)
                st.text_input("RESPONSABLE", value=trabajador.get("RESPONSABLE", ""), disabled=True)
                st.text_input("CARGO", value=trabajador.get("CARGO", ""), disabled=True)
            else:
                st.error("CC no encontrado.")
    else:
        name_input = st.text_input("Ingresa el Nombre:")
        if name_input:
            matches = [n for n in trabajadores_names if name_input.lower() in n.lower()]
            if matches:
                seleccionado = st.selectbox("Selecciona:", matches)
                trabajador = next((t for t in trabajadores_data if t.get("RESPONSABLE", "") == seleccionado), None)
                if trabajador:
                    st.success("Trabajador encontrado.")
                    st.text_input("CC", value=trabajador.get("CC CORRELATIVO ASIGNADO", ""), disabled=True)
                    st.text_input("RESPONSABLE", value=trabajador.get("RESPONSABLE", ""), disabled=True)
                    st.text_input("CARGO", value=trabajador.get("CARGO", ""), disabled=True)
            else:
                st.warning("No se encontraron coincidencias.")

    # Panel para agregar códigos: Ingreso Manual o Filtrado
    st.header("Agregar Documentos")
    st.info("Puedes ingresar códigos manualmente o filtrar por ECO y DISCIPLINA, luego presiona 'Agregar'.")
    tab_manual, tab_filtro = st.tabs(["Ingreso Manual", "Filtrar por ECO y DISCIPLINA"])

    with tab_manual:
        documento_manual = st.text_area("Ingrese los códigos (separados por comas):")
        if st.button("Agregar Manual"):
            new_codes = parse_multi_input(documento_manual)
            if new_codes:
                st.session_state["documento_codes"].extend(new_codes)
                st.success(f"Agregados {len(new_codes)} códigos.")
            else:
                st.warning("No se ingresaron códigos.")

    with tab_filtro:
        try:
            ws_log_sheet = sheet_log.worksheet("LOG")
            all_vals = ws_log_sheet.get_all_values()
            if len(all_vals) < 16:
                st.warning("No hay suficientes datos en la hoja LOG.")
            else:
                header = [col.strip() for col in all_vals[15]]
                def deduplicate_header(cols):
                    seen = {}
                    new_cols = []
                    for col in cols:
                        if col in seen:
                            seen[col] += 1
                            new_cols.append(f"{col}_{seen[col]}")
                        else:
                            seen[col] = 0
                            new_cols.append(col)
                    return new_cols
                header = deduplicate_header(header)
                data_rows = all_vals[16:]
                df = pd.DataFrame(data_rows, columns=header)

                for col in ["ECO", "DISCIPLINA", "N° ENTREGABLE SQM"]:
                    if col not in df.columns:
                        st.error(f"Falta la columna {col} en la hoja LOG.")
                        return

                # Normalizar para evitar duplicados
                df["ECO"] = df["ECO"].str.strip().str.upper()
                df["DISCIPLINA"] = df["DISCIPLINA"].str.strip().str.upper()

                # Filtrar por ECO y luego por DISCIPLINA (cruzado)
                ecos_disponibles = sorted(df["ECO"].unique())
                selected_eco = st.multiselect("Seleccione ECO:", ecos_disponibles)
                df_filtrado = df.copy()
                if selected_eco:
                    df_filtrado = df_filtrado[df_filtrado["ECO"].isin(selected_eco)]

                disciplinas_disponibles = sorted(df_filtrado["DISCIPLINA"].unique())
                selected_disc = st.multiselect("Seleccione DISCIPLINA:", disciplinas_disponibles)
                if selected_disc:
                    df_filtrado = df_filtrado[df_filtrado["DISCIPLINA"].isin(selected_disc)]

                st.write("Resultado del filtrado:")
                st.dataframe(df_filtrado)

                if st.button("Agregar Filtrados"):
                    codes_to_add = df_filtrado["N° ENTREGABLE SQM"].apply(lambda x: x.strip()).unique().tolist()
                    st.session_state["documento_codes"].extend(codes_to_add)
                    st.success(f"Agregados {len(codes_to_add)} códigos desde el filtrado.")
        except Exception as e:
            st.error(f"Error en el filtrado: {e}")

    st.subheader("Códigos agregados:")
    if st.session_state["documento_codes"]:
        st.write(st.session_state["documento_codes"])
    else:
        st.write("No hay códigos agregados todavía.")

    # Datos generales para el registro
    st.header("Datos Generales para el Registro")
    carpeta = st.text_input("Carpeta:")
    codigo_documento = st.text_input("Código del Documento (N° ENTREGABLE SQM): (Opcional)")
    if codigo_documento:
        if st.button("Agregar Documento Individual"):
            st.session_state["documento_codes"].append(codigo_documento.strip())
            st.success(f"Documento '{codigo_documento}' agregado.")
            st.experimental_rerun()

    cantidad = st.number_input("Cantidad:", min_value=1, step=1, value=1)
    fecha = st.date_input("Fecha:", value=datetime.now())
    observaciones = st.text_area("Observaciones:")

    if st.button("Guardar Registros"):
        if not trabajador:
            st.error("Selecciona un trabajador primero.")
            return
        if not st.session_state["documento_codes"]:
            st.error("No se han agregado códigos.")
            return

        errores = []
        for codigo in st.session_state["documento_codes"]:
            plano_data = lookup_plano_data(sheet_log, codigo)
            if plano_data:
                eco = plano_data.get("eco", "")
                tipo_doc = plano_data.get("tipo_doc", "")
                descripcion = plano_data.get("descripcion", "")
                disciplina = plano_data.get("disciplina", "")
                rev = plano_data.get("rev", "")
            else:
                eco = tipo_doc = descripcion = disciplina = rev = ""

            item_value, new_row = get_item_and_next_row(ws_doc_entregados, start_row=29)
            cc_val = str(trabajador.get("CC CORRELATIVO ASIGNADO", "")).strip()

            row_data = [
                "",
                item_value,
                cc_val,
                carpeta,
                CONTRATO,
                eco,
                tipo_doc,
                codigo,
                descripcion,
                rev,
                disciplina,
                cantidad,
                trabajador.get("RESPONSABLE", ""),
                trabajador.get("CARGO", ""),
                fecha.strftime("%d/%m/%Y"),
                observaciones,
                ENTREGADO_POR
            ]
            try:
                update_row(ws_doc_entregados, new_row, row_data, start_col=1)
                source_row = new_row - 2
                if source_row >= 29:
                    copy_format(ws_doc_entregados, source_row, new_row, start_col=1, end_col=17)
            except Exception as e:
                errores.append(f"{codigo}: {e}")

        if errores:
            st.error("Errores al guardar:\n" + "\n".join(errores))
        else:
            st.success("Todos los registros se guardaron exitosamente.")
            st.session_state["documento_codes"] = []

if __name__ == '__main__':
    main()
