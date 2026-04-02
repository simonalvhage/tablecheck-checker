pipeline {
    agent {
        docker {
            image 'mcr.microsoft.com/playwright/python:v1.58.0-noble'
            args '--ipc=host'
        }
    }

    parameters {
        string(
            name: 'TABLECHECK_URL',
            defaultValue: 'https://www.tablecheck.com/en/shops/hatsunezushi/reserve',
            description: 'TableCheck reservation URL'
        )
        string(
            name: 'PARTY_SIZE',
            defaultValue: '2',
            description: 'Number of guests'
        )
        string(
            name: 'START_DATE',
            defaultValue: '2026-05-09',
            description: 'Start date (YYYY-MM-DD)'
        )
        string(
            name: 'END_DATE',
            defaultValue: '2026-05-21',
            description: 'End date (YYYY-MM-DD)'
        )
        string(
            name: 'NOTIFY_EMAIL',
            defaultValue: 'simon.alvhage@gmail.com',
            description: 'Email address for availability alerts'
        )
    }

    triggers {
        cron('H/30 * * * *')
    }

    options {
        timeout(time: 10, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    stages {
        stage('Install dependencies') {
            steps {
                sh '''
                    pip install playwright==1.58.0 --break-system-packages --quiet 2>/dev/null || true
                    playwright install chromium --with-deps 2>/dev/null || true
                '''
            }
        }

        stage('Check availability') {
            steps {
                sh """
                    export TABLECHECK_URL="${params.TABLECHECK_URL}"
                    export PARTY_SIZE="${params.PARTY_SIZE}"
                    export START_DATE="${params.START_DATE}"
                    export END_DATE="${params.END_DATE}"
                    export OUTPUT_FILE="results.json"

                    python tablecheck.py || true
                """
            }
        }

        stage('Notify if available') {
            when {
                expression {
                    try {
                        def results = readFile('results.json')
                        def json = new HashMap(new groovy.json.JsonSlurper().parseText(results))
                        return json.available && json.available.size() > 0
                    } catch (Exception e) {
                        return false
                    }
                }
            }
            steps {
                script {
                    def results = readFile('results.json')
                    def json = new HashMap(new groovy.json.JsonSlurper().parseText(results))
                    def available = new HashMap(json.available ?: [:])

                    def body = """<h2>🍣 TableCheck Availability Found!</h2>
                        <p><strong>Restaurant:</strong> ${params.TABLECHECK_URL}</p>
                        <p><strong>Party size:</strong> ${params.PARTY_SIZE}</p>
                        <p><strong>Date range:</strong> ${params.START_DATE} → ${params.END_DATE}</p>
                        <hr/>
                        <h3>Available slots:</h3>
                        <table border="1" cellpadding="6" cellspacing="0">
                        <tr><th>Date</th><th>Times</th></tr>"""

                    available.each { day, slots ->
                        body += "<tr><td>${day}</td><td>${slots.join(', ')}</td></tr>"
                    }

                    body += """</table>
                        <br/>
                        <p><a href="${params.TABLECHECK_URL}">Book now →</a></p>
                        <hr/>
                        <p><small>Jenkins build: ${env.BUILD_URL}</small></p>"""

                    mail(
                        to: params.NOTIFY_EMAIL,
                        subject: "🍣 Table available! ${params.START_DATE}–${params.END_DATE}",
                        body: body,
                        mimeType: 'text/html'
                    )
                }
            }
        }
    }

    post {
        failure {
            script {
                if (params.NOTIFY_EMAIL) {
                    mail(
                        to: params.NOTIFY_EMAIL,
                        subject: "⚠️ TableCheck scraper FAILED – ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                        body: "Pipeline misslyckades.\nLoggar: ${env.BUILD_URL}console"
                    )
                }
            }
        }
        always {
            archiveArtifacts artifacts: 'results.json', allowEmptyArchive: true
        }
    }
}
