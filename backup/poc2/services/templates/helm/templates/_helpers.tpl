{{/* 공용 이름 헬퍼 */}}
{{- define "fed-model.fullname" -}}
{{- printf "%s-%s" .Release.Name .Values.model.name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
