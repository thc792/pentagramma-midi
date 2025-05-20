# api/index.py

from flask import Flask, request, jsonify
from flask_cors import CORS
from music21 import converter, stream, note, chord, duration
# from music21 import configure # Probabilmente non necessario su Vercel
import base64
import io
import traceback
import os
import tempfile

NOTE_SPLIT_POINT = 60
DEFAULT_PPQ = 480

app = Flask(__name__)
# Configurazione CORS per Vercel:
# Aggiornato per riflettere i path con /api/ se necessario per la granularità,
# ma r"/api/*" dovrebbe già coprire tutto ciò che inizia con /api/
CORS(app, resources={r"/api/*": {"origins": "*"}}) # Permette tutte le origini per /api/*

@app.route('/api/', methods=['GET']) # MODIFICATO: Aggiunto /api/
def handle_root_redirect_to_api():
    # Questo endpoint sarà accessibile come /api/
    return "Backend music21 (API) attivo. L'endpoint principale è /api/process_midi."

@app.route('/api/process_midi', methods=['POST']) # MODIFICATO: Aggiunto /api/
def process_midi():
    # Modificato il messaggio di log per riflettere il path completo che Flask vede
    print("\n--- Ricevuta richiesta POST su /api/process_midi (vista da Flask come /api/process_midi) ---")

    data = request.json
    if not data or 'midiData' not in data or not data['midiData']:
        print("Errore: Dati MIDI 'midiData' mancanti o vuoti.")
        return jsonify({"error": "Nessun dato MIDI inviato o formato JSON non valido."}), 400

    temp_file_path = None

    try:
        base64_string_with_header = data['midiData']
        if ',' in base64_string_with_header:
            header, base64_string = base64_string_with_header.split(',', 1)
        else:
            base64_string = base64_string_with_header

        midi_bytes = base64.b64decode(base64_string)

        try:
            print("Inizio analisi music21 direttamente dai byte MIDI...")
            fp = io.BytesIO(midi_bytes)
            midi_stream = converter.parse(fp, format='midi')
            fp.close()
            print("Analisi MIDI con music21 completata dai byte.")
        except Exception as parse_byte_e:
            print(f"ATTENZIONE: Fallita analisi music21 da byte: {parse_byte_e}. Provo con file temporaneo.")
            temp_dir = tempfile.gettempdir()
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mid', mode='wb', dir=temp_dir) as temp_file:
                temp_file.write(midi_bytes)
                temp_file_path = temp_file.name

            print(f"Inizio analisi music21 da file temporaneo '{os.path.basename(temp_file_path)}'...")
            midi_stream = converter.parse(temp_file_path, format='midi')
            print("Analisi MIDI con music21 completata da file.")

        extracted_metadata = {}
        extracted_notes_list = []
        note_id_counter = 0

        time_sig_obj = midi_stream.flat.getElementsByClass('TimeSignature')
        if time_sig_obj:
            try:
                numerator = time_sig_obj[0].numerator
                denominator = time_sig_obj[0].denominator
                extracted_metadata['timeSignature'] = f"{numerator}/{denominator}"
            except Exception as ts_e:
                print(f"ATTENZIONE: Errore estrazione TimeSignature: {ts_e}. Uso default 4/4.")
                extracted_metadata['timeSignature'] = "4/4"
        else:
            extracted_metadata['timeSignature'] = "4/4"

        key_sig_name = "C"
        try:
            key_analysis = midi_stream.analyze('key')
            if key_analysis:
                vexflow_key_name = key_analysis.tonic.name
                if key_analysis.mode == 'minor':
                    vexflow_key_name += 'm'
                key_sig_name = vexflow_key_name
                print(f"DEBUG: Key Signature estratta (analisi music21): {key_sig_name}")
        except Exception as key_analyze_e:
            print(f"ATTENZIONE: Errore analisi Key Signature con music21: {key_analyze_e}. Uso default C.")

        extracted_metadata['keySignature'] = key_sig_name

        tempo_elements = midi_stream.flat.getElementsByClass(['TempoIndication', 'MetronomeMark'])
        found_qpm = None
        for el in tempo_elements:
            try:
                current_qpm = el.getQuarterNotesPerMinute()
                if current_qpm is not None and current_qpm > 0:
                    found_qpm = current_qpm
                    break
            except AttributeError:
                pass

        if found_qpm is not None:
            extracted_metadata['tempo'] = int(60000000 / found_qpm)
        else:
            extracted_metadata['tempo'] = 500000 # Default a 120 QPM

        extracted_metadata['ppq'] = DEFAULT_PPQ

        for element in midi_stream.flat.notesAndRests:
            try:
                original_ticks = int(round(element.offset * extracted_metadata.get('ppq', DEFAULT_PPQ)))
                duration_ticks = int(round(element.duration.quarterLength * extracted_metadata.get('ppq', DEFAULT_PPQ)))
            except Exception as calc_e:
                print(f"ATTENZIONE: Errore calcolo ticks/duration per elemento a offset {element.offset}: {calc_e}")
                original_ticks = 0
                duration_ticks = 1

            if isinstance(element, note.Note):
                accidental_type = None
                if element.pitch and element.pitch.accidental:
                    try:
                        if hasattr(element.pitch.accidental, 'type') and element.pitch.accidental.type != 'natural':
                            if element.pitch.accidental.type == 'sharp': accidental_type = '#'
                            elif element.pitch.accidental.type == 'flat': accidental_type = 'b'
                            elif element.pitch.accidental.type == 'double-sharp': accidental_type = '##'
                            elif element.pitch.accidental.type == 'double-flat': accidental_type = 'bb'
                            else: accidental_type = element.pitch.accidental.type
                        elif hasattr(element.pitch.accidental, 'alter') and element.pitch.accidental.alter != 0:
                            alter_value = element.pitch.accidental.alter
                            if alter_value == -1: accidental_type = 'b'
                            elif alter_value == 1: accidental_type = '#'
                            elif alter_value == -2: accidental_type = 'bb'
                            elif alter_value == 2: accidental_type = '##'
                    except Exception as acc_e:
                        print(f"ATTENZIONE: Errore estrazione accidental (type/alter) per nota a offset {element.offset}: {acc_e}")

                extracted_notes_list.append({
                    'id': f'note-{note_id_counter}',
                    'midi': element.pitch.midi,
                    'ticks': original_ticks,
                    'durationTicks': duration_ticks,
                    'track': 0, 'channel': 0,
                    'velocity': element.volume.velocity if element.volume.velocity is not None else 64,
                    'accidental': accidental_type,
                    'noteNameWithOctave': element.pitch.nameWithOctave
                })
                note_id_counter += 1

            elif isinstance(element, chord.Chord):
                for single_note_in_chord in element.notes:
                    accidental_type = None
                    if single_note_in_chord.pitch and single_note_in_chord.pitch.accidental:
                        try:
                            if hasattr(single_note_in_chord.pitch.accidental, 'type') and single_note_in_chord.pitch.accidental.type != 'natural':
                                if single_note_in_chord.pitch.accidental.type == 'sharp': accidental_type = '#'
                                elif single_note_in_chord.pitch.accidental.type == 'flat': accidental_type = 'b'
                                elif single_note_in_chord.pitch.accidental.type == 'double-sharp': accidental_type = '##'
                                elif single_note_in_chord.pitch.accidental.type == 'double-flat': accidental_type = 'bb'
                                else: accidental_type = single_note_in_chord.pitch.accidental.type
                            elif hasattr(single_note_in_chord.pitch.accidental, 'alter') and single_note_in_chord.pitch.accidental.alter != 0:
                                alter_value = single_note_in_chord.pitch.accidental.alter
                                if alter_value == -1: accidental_type = 'b'
                                elif alter_value == 1: accidental_type = '#'
                                elif alter_value == -2: accidental_type = 'bb'
                                elif alter_value == 2: accidental_type = '##'
                        except Exception as acc_e:
                            print(f"ATTENZIONE: Errore estrazione accidental (type/alter) per nota in accordo a offset {element.offset}: {acc_e}")

                    extracted_notes_list.append({
                        'id': f'note-{note_id_counter}',
                        'midi': single_note_in_chord.pitch.midi,
                        'ticks': original_ticks,
                        'durationTicks': duration_ticks,
                        'track': 0, 'channel': 0,
                        'velocity': getattr(single_note_in_chord.volume, 'velocity', element.volume.velocity if element.volume.velocity is not None else 64),
                        'accidental': accidental_type,
                        'noteNameWithOctave': single_note_in_chord.pitch.nameWithOctave
                    })
                    note_id_counter += 1

        extracted_notes_list.sort(key=lambda x: (x['ticks'], x.get('midi', 0)))
        response_data = { "metadata": extracted_metadata, "allParsedNotes": extracted_notes_list }
        return jsonify(response_data)

    except Exception as e:
        print(f"\n!!! Errore CRITICO durante l'elaborazione MIDI nel backend: {e}")
        traceback.print_exc()
        error_response = { "error": f"Errore interno del server durante l'elaborazione MIDI: {str(e)}", "detail": traceback.format_exc() }
        print("Invio risposta di errore 500 al frontend.")
        return jsonify(error_response), 500

    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                print(f"ATTENZIONE: Impossibile cancellare file temporaneo {temp_file_path}: {e}")

# Nessuna chiamata app.run() qui sotto, Gunicorn si occuperà di eseguire l'app.
# if __name__ == '__main__':
#     app.run(debug=True) # Questa riga è utile per test locali, ma non per Gunicorn su Vercel