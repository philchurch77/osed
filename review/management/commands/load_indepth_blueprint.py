"""
Load all in-depth review areas and sub-sections from the Ofsted Inspection
Toolkit Blueprint (v1.1, November 2025).

Data is embedded here so no Excel file is required at runtime.
Run with:  python manage.py load_indepth_blueprint [--clear]
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from review.models import InDepthArea, InDepthSubSection

# ---------------------------------------------------------------------------
# Blueprint data
# ---------------------------------------------------------------------------

_NOT_MET_DESC = (
    "The school's safeguarding arrangements do not meet the requirements of statutory "
    "guidance (Keeping Children Safe in Education). One or more critical requirements "
    "are absent or ineffective. The school cannot be judged better than Requires "
    "Improvement overall."
)
_MET_DESC = (
    "The school's safeguarding arrangements meet all requirements of statutory guidance. "
    "Processes are embedded, staff are trained, record-keeping is appropriate, and the "
    "designated safeguarding lead is effective."
)

BLUEPRINT = [
    {
        "name": "Safeguarding",
        "order": 1,
        "is_safeguarding": True,
        "purpose": (
            "To evaluate whether the school has effective safeguarding arrangements "
            "that protect all pupils, including the most vulnerable."
        ),
        "subsections": [
            {
                "name": "Statutory Requirements & Policies",
                "order": 1,
                "overview": "Does the school have all required safeguarding policies and meet KCSIE statutory requirements?",
                "evidence_criteria": (
                    "• Child protection policy is up to date, reviewed annually, reflects KCSIE\n"
                    "• Policy covers all required elements: online safety, peer-on-peer abuse, staff conduct, allegations against staff\n"
                    "• Single central record (SCR) is complete and accurate for all staff/volunteers\n"
                    "• Safer recruitment procedures are followed; all pre-employment checks completed\n"
                    "• Governors/trustees have received appropriate safeguarding training"
                ),
                "not_met_descriptor": _NOT_MET_DESC,
                "met_descriptor": _MET_DESC,
            },
            {
                "name": "Designated Safeguarding Lead (DSL)",
                "order": 2,
                "overview": "Is the DSL (and deputies) effective, appropriately trained and available?",
                "evidence_criteria": (
                    "• DSL is a senior leader with appropriate authority and time allocation\n"
                    "• DSL has received training updated at least every two years\n"
                    "• Deputies are trained and cover DSL absence effectively\n"
                    "• DSL maintains up-to-date knowledge of local safeguarding arrangements\n"
                    "• DSL acts as source of support and advice for all staff"
                ),
                "not_met_descriptor": _NOT_MET_DESC,
                "met_descriptor": _MET_DESC,
            },
            {
                "name": "Staff Knowledge & Culture",
                "order": 3,
                "overview": "Do staff know how to identify and report concerns? Is there a culture of safeguarding vigilance?",
                "evidence_criteria": (
                    "• All staff receive safeguarding training at induction and annually thereafter\n"
                    "• Staff can articulate how to report a concern and to whom\n"
                    "• School culture promotes an 'it could happen here' mindset\n"
                    "• Low-level concerns are recorded and reviewed for patterns\n"
                    "• Pupils feel safe and know how to report concerns"
                ),
                "not_met_descriptor": _NOT_MET_DESC,
                "met_descriptor": _MET_DESC,
            },
            {
                "name": "Record Keeping & Referrals",
                "order": 4,
                "overview": "Are safeguarding records maintained appropriately and referrals made in a timely way?",
                "evidence_criteria": (
                    "• Safeguarding records are detailed, chronological and securely stored\n"
                    "• Records follow pupils when they transfer to another school\n"
                    "• Referrals to children's social care are made promptly when thresholds met\n"
                    "• School engages with multi-agency safeguarding arrangements\n"
                    "• Unexplained absences and attendance patterns are followed up"
                ),
                "not_met_descriptor": _NOT_MET_DESC,
                "met_descriptor": _MET_DESC,
            },
            {
                "name": "Site Safety & Filtering/Monitoring",
                "order": 5,
                "overview": "Are the school's physical environment and online systems safe for pupils?",
                "evidence_criteria": (
                    "• Site security measures are appropriate and effective\n"
                    "• Filtering and monitoring systems are in place for school internet/devices\n"
                    "• School has an online safety policy and teaches online safety\n"
                    "• Visitors are managed appropriately; signing-in procedures followed\n"
                    "• Risk assessments for off-site activities are completed"
                ),
                "not_met_descriptor": _NOT_MET_DESC,
                "met_descriptor": _MET_DESC,
            },
        ],
    },
    {
        "name": "Quality of Education",
        "order": 2,
        "is_safeguarding": False,
        "purpose": (
            "To evaluate the extent to which the school's curriculum and teaching lead "
            "to high-quality learning and strong outcomes for all pupils."
        ),
        "subsections": [
            {
                "name": "Curriculum Intent",
                "order": 1,
                "overview": "Does the school have an ambitious, coherently planned curriculum for all pupils?",
                "evidence_criteria": (
                    "• Curriculum is ambitious and designed to give all pupils, including SEND and "
                    "disadvantaged, the knowledge and skills they need\n"
                    "• Curriculum is coherently planned and sequenced to build knowledge over time\n"
                    "• Leaders articulate a clear rationale for curriculum choices\n"
                    "• Curriculum meets statutory requirements and goes beyond where appropriate\n"
                    "• Curriculum is not narrowed to focus only on exam content\n"
                    "• Reading is given high priority across the curriculum"
                ),
                "urgent_improvement_descriptor": "Significant weaknesses in curriculum intent mean that pupils' learning and/or progress are seriously undermined. Immediate action is required.",
                "needs_attention_descriptor": "There are notable weaknesses in curriculum intent. Pupils' learning is hampered and outcomes are below acceptable levels.",
                "expected_descriptor": "Curriculum intent is broadly effective. Most pupils learn well and make reasonable progress, though some gaps or inconsistencies remain.",
                "strong_descriptor": "Curriculum intent is strong. Pupils learn well, make good progress and outcomes are above expectations in most respects.",
                "exceptional_descriptor": "Curriculum intent is exceptional. Pupils learn extremely well, make excellent progress, and outcomes are outstanding across all groups.",
            },
            {
                "name": "Curriculum Implementation",
                "order": 2,
                "overview": "Is the curriculum taught effectively so that pupils learn and remember content?",
                "evidence_criteria": (
                    "• Teachers have strong subject knowledge and present content clearly\n"
                    "• Teaching builds on prior knowledge and addresses gaps\n"
                    "• Teachers use assessment to check understanding and adapt teaching\n"
                    "• Pupils are helped to remember what they have learned (retrieval practice, spaced learning)\n"
                    "• Teaching strategies are appropriate to the content and pupils' needs\n"
                    "• SEND pupils receive appropriate support and adaptations without limiting ambition\n"
                    "• Pupils are engaged and on task"
                ),
                "urgent_improvement_descriptor": "Significant weaknesses in curriculum implementation mean that pupils' learning and/or progress are seriously undermined. Immediate action is required.",
                "needs_attention_descriptor": "There are notable weaknesses in curriculum implementation. Pupils' learning is hampered and outcomes are below acceptable levels.",
                "expected_descriptor": "Curriculum implementation is broadly effective. Most pupils learn well and make reasonable progress, though some gaps or inconsistencies remain.",
                "strong_descriptor": "Curriculum implementation is strong. Pupils learn well, make good progress and outcomes are above expectations in most respects.",
                "exceptional_descriptor": "Curriculum implementation is exceptional. Pupils learn extremely well, make excellent progress, and outcomes are outstanding across all groups.",
            },
            {
                "name": "Curriculum Impact",
                "order": 3,
                "overview": "Do pupils know and remember more as a result of the curriculum? Are outcomes strong?",
                "evidence_criteria": (
                    "• Pupils demonstrate secure knowledge and understanding across subjects\n"
                    "• Pupils can recall prior learning and make connections\n"
                    "• Outcomes in national assessments / qualifications are at least in line with "
                    "national averages for similar schools\n"
                    "• Gaps between pupil groups (disadvantaged, SEND, EAL) are narrowing or absent\n"
                    "• Pupils are prepared for the next stage of education, employment or training\n"
                    "• Attendance and exclusion rates do not disadvantage outcomes for groups"
                ),
                "urgent_improvement_descriptor": "Significant weaknesses in curriculum impact mean that pupils' learning and/or progress are seriously undermined. Immediate action is required.",
                "needs_attention_descriptor": "There are notable weaknesses in curriculum impact. Pupils' learning is hampered and outcomes are below acceptable levels.",
                "expected_descriptor": "Curriculum impact is broadly effective. Most pupils learn well and make reasonable progress, though some gaps or inconsistencies remain.",
                "strong_descriptor": "Curriculum impact is strong. Pupils learn well, make good progress and outcomes are above expectations in most respects.",
                "exceptional_descriptor": "Curriculum impact is exceptional. Pupils learn extremely well, make excellent progress, and outcomes are outstanding across all groups.",
            },
            {
                "name": "Assessment",
                "order": 4,
                "overview": "Is assessment used effectively to support learning rather than as a performative exercise?",
                "evidence_criteria": (
                    "• Assessment is used to check what pupils know and to inform teaching\n"
                    "• Assessment does not create unnecessary pupil or teacher workload\n"
                    "• Marking and feedback are purposeful and acted upon by pupils\n"
                    "• Assessment information is used to identify pupils who need additional support\n"
                    "• Leaders monitor assessment data and take action to address gaps"
                ),
                "urgent_improvement_descriptor": "Significant weaknesses in assessment practice mean that pupils' learning and/or progress are seriously undermined. Immediate action is required.",
                "needs_attention_descriptor": "There are notable weaknesses in assessment practice. Pupils' learning is hampered and outcomes are below acceptable levels.",
                "expected_descriptor": "Assessment practice is broadly effective. Most pupils learn well and make reasonable progress, though some gaps or inconsistencies remain.",
                "strong_descriptor": "Assessment practice is strong. Pupils learn well, make good progress and outcomes are above expectations in most respects.",
                "exceptional_descriptor": "Assessment practice is exceptional. Pupils learn extremely well, make excellent progress, and outcomes are outstanding across all groups.",
            },
            {
                "name": "Reading",
                "order": 5,
                "overview": "Do all pupils develop the reading skills needed to access the curriculum?",
                "evidence_criteria": (
                    "• School has a structured, systematic phonics programme (primary) or reading "
                    "intervention programme (secondary)\n"
                    "• Pupils who fall behind in reading receive prompt, effective support\n"
                    "• Reading is promoted across the curriculum; pupils read widely and frequently\n"
                    "• Teachers read aloud to pupils; vocabulary is explicitly taught\n"
                    "• Pupils who struggle with reading are identified early and supported effectively"
                ),
                "urgent_improvement_descriptor": "Significant weaknesses in reading provision mean that pupils' learning and/or progress are seriously undermined. Immediate action is required.",
                "needs_attention_descriptor": "There are notable weaknesses in reading provision. Pupils' learning is hampered and outcomes are below acceptable levels.",
                "expected_descriptor": "Reading provision is broadly effective. Most pupils learn well and make reasonable progress, though some gaps or inconsistencies remain.",
                "strong_descriptor": "Reading provision is strong. Pupils learn well, make good progress and outcomes are above expectations in most respects.",
                "exceptional_descriptor": "Reading provision is exceptional. Pupils learn extremely well, make excellent progress, and outcomes are outstanding across all groups.",
            },
        ],
    },
    {
        "name": "Behaviour & Attitudes",
        "order": 3,
        "is_safeguarding": False,
        "purpose": (
            "To evaluate whether pupils' behaviour and attitudes support an effective learning "
            "environment and whether pupils feel safe."
        ),
        "subsections": [
            {
                "name": "Behaviour in Lessons",
                "order": 1,
                "overview": "Do pupils behave well in lessons and support a productive learning environment?",
                "evidence_criteria": (
                    "• Pupils are attentive and ready to learn\n"
                    "• Low-level disruption is rare; when it occurs, it is managed effectively\n"
                    "• Pupils follow instructions promptly\n"
                    "• Pupils treat each other and staff with respect\n"
                    "• The school's behaviour policy is applied consistently by all staff"
                ),
                "urgent_improvement_descriptor": "Behaviour or attitudes in lessons are unacceptable. Disruption, bullying or disengagement seriously undermine the school's work. Urgent improvement is required.",
                "needs_attention_descriptor": "There are notable problems with behaviour in lessons. Learning is frequently disrupted or significant numbers of pupils have poor attitudes. Action is needed.",
                "expected_descriptor": "Behaviour in lessons broadly meets expectations. Most pupils behave well and have positive attitudes, with some inconsistencies.",
                "strong_descriptor": "Behaviour in lessons is strong. Pupils consistently behave well, demonstrate positive attitudes and contribute to a calm, purposeful environment.",
                "exceptional_descriptor": "Behaviour in lessons is exceptional. Behaviour and attitudes are exemplary across the school. Pupils take pride in their school and support one another.",
            },
            {
                "name": "Behaviour Around School",
                "order": 2,
                "overview": "Do pupils behave well in corridors, at break and lunch, and in communal areas?",
                "evidence_criteria": (
                    "• The school's environment is calm and orderly\n"
                    "• Pupils move around the school safely and respectfully\n"
                    "• There is no evidence of significant intimidation or threatening behaviour\n"
                    "• Pupils' conduct at the start and end of the school day is appropriate"
                ),
                "urgent_improvement_descriptor": "Behaviour around school is unacceptable. Disruption, bullying or disengagement seriously undermine the school's work. Urgent improvement is required.",
                "needs_attention_descriptor": "There are notable problems with behaviour around school. Learning is frequently disrupted or significant numbers of pupils have poor attitudes. Action is needed.",
                "expected_descriptor": "Behaviour around school broadly meets expectations. Most pupils behave well and have positive attitudes, with some inconsistencies.",
                "strong_descriptor": "Behaviour around school is strong. Pupils consistently behave well and contribute to a calm, purposeful environment.",
                "exceptional_descriptor": "Behaviour around school is exceptional. Behaviour and attitudes are exemplary. Pupils take pride in their school and support one another.",
            },
            {
                "name": "Attendance & Punctuality",
                "order": 3,
                "overview": "Do pupils attend school regularly and arrive on time?",
                "evidence_criteria": (
                    "• Overall attendance is at least in line with national average\n"
                    "• Persistent absence rates are low, or improving for all groups\n"
                    "• Disadvantaged and SEND pupils' attendance is monitored and supported\n"
                    "• School follows up all absences promptly and consistently\n"
                    "• Pupils arrive to school and lessons on time"
                ),
                "urgent_improvement_descriptor": "Attendance and punctuality are unacceptable and seriously undermine the school's work. Urgent improvement is required.",
                "needs_attention_descriptor": "There are notable problems with attendance and punctuality. Significant numbers of pupils have persistently poor attendance. Action is needed.",
                "expected_descriptor": "Attendance and punctuality broadly meets expectations. Most pupils attend well, with some inconsistencies.",
                "strong_descriptor": "Attendance and punctuality is strong. Pupils consistently attend and arrive on time; the school actively supports good attendance.",
                "exceptional_descriptor": "Attendance and punctuality is exceptional. Attendance is outstanding across all groups and the school is a model of best practice.",
            },
            {
                "name": "Bullying & Peer Relationships",
                "order": 4,
                "overview": "Are pupils safe from bullying and do they have positive relationships?",
                "evidence_criteria": (
                    "• Bullying (including online) is rare; when it occurs, it is dealt with effectively\n"
                    "• Pupils report feeling safe from bullying and harassment\n"
                    "• The school's anti-bullying policy is clear and understood by pupils and parents\n"
                    "• Pupils treat each other with kindness and respect\n"
                    "• Discriminatory behaviour (racist, homophobic, sexist etc.) is challenged robustly"
                ),
                "urgent_improvement_descriptor": "Bullying and peer relationships are unacceptable. Pupils do not feel safe. Urgent improvement is required.",
                "needs_attention_descriptor": "There are notable problems with bullying and peer relationships. Pupils' wellbeing and safety are at risk. Action is needed.",
                "expected_descriptor": "Bullying and peer relationships broadly meet expectations. Most pupils feel safe and relationships are positive, with some areas for improvement.",
                "strong_descriptor": "Bullying and peer relationships are strong. Pupils feel safe, relationships are respectful, and the school responds effectively to any concerns.",
                "exceptional_descriptor": "Bullying and peer relationships are exceptional. Pupils are exemplary in how they treat one another; bullying is extremely rare and swiftly addressed.",
            },
            {
                "name": "Exclusions & Suspensions",
                "order": 5,
                "overview": "Are exclusions and suspensions used appropriately and equitably?",
                "evidence_criteria": (
                    "• Suspension and exclusion rates are not disproportionate for any pupil group\n"
                    "• Alternative provision for excluded pupils is of good quality\n"
                    "• Internal exclusion/isolation rooms are used appropriately with learning provided\n"
                    "• The school can demonstrate that exclusions are a last resort\n"
                    "• Pupils returning from suspension receive appropriate reintegration support"
                ),
                "urgent_improvement_descriptor": "Exclusion and suspension practice is unacceptable. Rates are disproportionate or pupils' rights are not upheld. Urgent improvement is required.",
                "needs_attention_descriptor": "There are notable problems with exclusion and suspension practice. Action is needed to ensure equitable and appropriate use.",
                "expected_descriptor": "Exclusion and suspension practice broadly meets expectations. Rates are broadly proportionate and procedures are followed.",
                "strong_descriptor": "Exclusion and suspension practice is strong. Rates are low, equitable, and the school demonstrates exclusion is a last resort.",
                "exceptional_descriptor": "Exclusion and suspension practice is exceptional. The school is a model of restorative, inclusive practice with exemplary outcomes for all groups.",
            },
        ],
    },
    {
        "name": "Personal Development",
        "order": 4,
        "is_safeguarding": False,
        "purpose": (
            "To evaluate how well the school develops pupils' character, resilience, confidence, "
            "and readiness for life in modern Britain."
        ),
        "subsections": [
            {
                "name": "SMSC & Character",
                "order": 1,
                "overview": "Does the school actively develop pupils' spiritual, moral, social and cultural development and character?",
                "evidence_criteria": (
                    "• SMSC is woven throughout the curriculum and wider school life\n"
                    "• Pupils develop resilience, confidence and a growth mindset\n"
                    "• School offers structured opportunities for pupils to take on responsibility\n"
                    "• Pupils demonstrate respect for diversity and difference\n"
                    "• Extra-curricular activities and enrichment are accessible to all pupils"
                ),
                "urgent_improvement_descriptor": "Provision for SMSC and character development is seriously lacking. Pupils are not receiving the personal development they need. Urgent action is required.",
                "needs_attention_descriptor": "Provision for SMSC and character development has significant gaps. Pupils' personal development is hampered in important ways.",
                "expected_descriptor": "Provision for SMSC and character development meets expectations. Most pupils develop well personally, though there are areas to improve.",
                "strong_descriptor": "Provision for SMSC and character development is strong. Pupils develop well, are well prepared for life in modern Britain and have broad opportunities.",
                "exceptional_descriptor": "Provision for SMSC and character development is exceptional. Pupils thrive personally and are outstandingly prepared for adult life.",
            },
            {
                "name": "RSHE / PSHE",
                "order": 2,
                "overview": "Is RSHE and PSHE provision high quality, age-appropriate and effective?",
                "evidence_criteria": (
                    "• RSHE meets statutory requirements and is delivered with appropriate expertise\n"
                    "• Curriculum covers: health, relationships, sex education (where applicable), online safety, consent\n"
                    "• Content is age-appropriate and delivered sensitively\n"
                    "• Pupils can access support if issues arise from RSHE content\n"
                    "• Parents are consulted on content; withdrawal procedures followed correctly"
                ),
                "urgent_improvement_descriptor": "Provision for RSHE/PSHE is seriously lacking. Pupils are not receiving the personal development they need. Urgent action is required.",
                "needs_attention_descriptor": "Provision for RSHE/PSHE has significant gaps. Pupils' personal development is hampered in important ways.",
                "expected_descriptor": "Provision for RSHE/PSHE meets expectations. Most pupils develop well personally, though there are areas to improve.",
                "strong_descriptor": "Provision for RSHE/PSHE is strong. Pupils develop well and are well prepared for life in modern Britain.",
                "exceptional_descriptor": "Provision for RSHE/PSHE is exceptional. Pupils thrive personally and are outstandingly prepared for adult life.",
            },
            {
                "name": "Careers Education",
                "order": 3,
                "overview": "Are pupils well prepared for their next steps through high-quality careers education and guidance?",
                "evidence_criteria": (
                    "• Careers programme is comprehensive, impartial and age-appropriate (Baker Clause met)\n"
                    "• All pupils in Y7–11 receive meaningful encounters with employers\n"
                    "• Careers guidance is personalised; disadvantaged pupils receive additional support\n"
                    "• Pupils know about a range of pathways: apprenticeships, FE, HE, employment\n"
                    "• Destinations data is tracked and used to evaluate and improve the programme"
                ),
                "urgent_improvement_descriptor": "Provision for careers education is seriously lacking. Pupils are not receiving the personal development they need. Urgent action is required.",
                "needs_attention_descriptor": "Provision for careers education has significant gaps. Pupils' personal development is hampered in important ways.",
                "expected_descriptor": "Provision for careers education meets expectations. Most pupils develop well personally, though there are areas to improve.",
                "strong_descriptor": "Provision for careers education is strong. Pupils develop well and are well prepared for their next steps.",
                "exceptional_descriptor": "Provision for careers education is exceptional. Pupils thrive personally and are outstandingly prepared for adult life.",
            },
            {
                "name": "British Values & Citizenship",
                "order": 4,
                "overview": "Do pupils understand and respect fundamental British values?",
                "evidence_criteria": (
                    "• Democracy, rule of law, individual liberty, mutual respect and tolerance are promoted actively\n"
                    "• Pupils demonstrate understanding of how democracy and the law work\n"
                    "• School prevents radicalisation and extremism (Prevent duty fulfilled)\n"
                    "• Pupils are taught to challenge stereotypes and discrimination\n"
                    "• School council and pupil voice are meaningful and acted upon"
                ),
                "urgent_improvement_descriptor": "Provision for British values and citizenship is seriously lacking. Pupils are not receiving the personal development they need. Urgent action is required.",
                "needs_attention_descriptor": "Provision for British values and citizenship has significant gaps. Pupils' personal development is hampered in important ways.",
                "expected_descriptor": "Provision for British values and citizenship meets expectations. Most pupils develop well personally, though there are areas to improve.",
                "strong_descriptor": "Provision for British values and citizenship is strong. Pupils develop well and are well prepared for life in modern Britain.",
                "exceptional_descriptor": "Provision for British values and citizenship is exceptional. Pupils thrive personally and are outstandingly prepared for adult life.",
            },
            {
                "name": "Wider Opportunities & Enrichment",
                "order": 5,
                "overview": "Do pupils have access to a wide range of enriching activities that develop them as individuals?",
                "evidence_criteria": (
                    "• Broad range of clubs, trips, activities and leadership opportunities are available\n"
                    "• Disadvantaged pupils have equal access to enrichment activities\n"
                    "• Pupils develop interests, hobbies and skills outside the core curriculum\n"
                    "• Cultural capital is developed deliberately: arts, music, sport, volunteering\n"
                    "• Pupil premium is used effectively to remove barriers to participation"
                ),
                "urgent_improvement_descriptor": "Provision for wider opportunities and enrichment is seriously lacking. Pupils are not receiving the personal development they need. Urgent action is required.",
                "needs_attention_descriptor": "Provision for wider opportunities and enrichment has significant gaps. Pupils' personal development is hampered in important ways.",
                "expected_descriptor": "Provision for wider opportunities and enrichment meets expectations. Most pupils develop well personally, though there are areas to improve.",
                "strong_descriptor": "Provision for wider opportunities and enrichment is strong. Pupils develop well and have broad opportunities.",
                "exceptional_descriptor": "Provision for wider opportunities and enrichment is exceptional. Pupils thrive personally and are outstandingly prepared for adult life.",
            },
        ],
    },
    {
        "name": "Leadership & Management",
        "order": 5,
        "is_safeguarding": False,
        "purpose": (
            "To evaluate whether leaders create the conditions for high-quality education and "
            "manage the school effectively in the interests of all pupils."
        ),
        "subsections": [
            {
                "name": "Vision, Ethos & Strategy",
                "order": 1,
                "overview": "Do leaders have a clear, shared vision that drives improvement across the school?",
                "evidence_criteria": (
                    "• Leaders articulate a clear, ambitious vision for the school\n"
                    "• Vision is shared and understood by staff, pupils and parents\n"
                    "• Strategies to achieve the vision are coherent and evidence-informed\n"
                    "• Leaders review progress against priorities and adjust plans accordingly\n"
                    "• Leaders create a positive ethos where everyone feels valued"
                ),
                "urgent_improvement_descriptor": "Leadership and management of vision, ethos and strategy is failing. Fundamental weaknesses require immediate action.",
                "needs_attention_descriptor": "Leadership and management of vision, ethos and strategy has significant weaknesses that are limiting the school's effectiveness.",
                "expected_descriptor": "Leadership and management of vision, ethos and strategy is broadly effective. Most systems work well, though improvement is possible.",
                "strong_descriptor": "Leadership and management of vision, ethos and strategy is strong. Leaders are effective and drive continuous improvement.",
                "exceptional_descriptor": "Leadership and management of vision, ethos and strategy is exceptional. Leaders are highly effective and create the conditions for excellence throughout.",
            },
            {
                "name": "Staff Development & Wellbeing",
                "order": 2,
                "overview": "Do leaders develop staff effectively and manage workload and wellbeing?",
                "evidence_criteria": (
                    "• CPD is high quality, relevant and embedded in day-to-day practice\n"
                    "• Staff have access to coaching, mentoring and leadership development\n"
                    "• Workload is managed so it does not undermine staff wellbeing\n"
                    "• Staff feel valued and supported; retention and recruitment is not a serious concern\n"
                    "• Leaders model professional behaviour and set high expectations for all"
                ),
                "urgent_improvement_descriptor": "Leadership and management of staff development and wellbeing is failing. Fundamental weaknesses require immediate action.",
                "needs_attention_descriptor": "Leadership and management of staff development and wellbeing has significant weaknesses that are limiting the school's effectiveness.",
                "expected_descriptor": "Leadership and management of staff development and wellbeing is broadly effective. Most systems work well, though improvement is possible.",
                "strong_descriptor": "Leadership and management of staff development and wellbeing is strong. Leaders are effective and drive continuous improvement.",
                "exceptional_descriptor": "Leadership and management of staff development and wellbeing is exceptional. Leaders are highly effective and create the conditions for excellence throughout.",
            },
            {
                "name": "Governance & Accountability",
                "order": 3,
                "overview": "Do governors/trustees hold leaders to account effectively and provide appropriate support?",
                "evidence_criteria": (
                    "• Governors have the skills and knowledge needed to fulfil their responsibilities\n"
                    "• Governors receive appropriate information and ask challenging questions\n"
                    "• Governors hold the headteacher to account for pupil outcomes and use of resources\n"
                    "• Governance arrangements are transparent and free from conflicts of interest\n"
                    "• Governors ensure statutory duties are met, including SEND, equality and safeguarding"
                ),
                "urgent_improvement_descriptor": "Leadership and management of governance and accountability is failing. Fundamental weaknesses require immediate action.",
                "needs_attention_descriptor": "Leadership and management of governance and accountability has significant weaknesses that are limiting the school's effectiveness.",
                "expected_descriptor": "Leadership and management of governance and accountability is broadly effective. Most systems work well, though improvement is possible.",
                "strong_descriptor": "Leadership and management of governance and accountability is strong. Governors are effective and hold leaders to account.",
                "exceptional_descriptor": "Leadership and management of governance and accountability is exceptional. Governance is highly effective and creates the conditions for excellence.",
            },
            {
                "name": "Safeguarding Leadership",
                "order": 4,
                "overview": "Do leaders prioritise safeguarding and create a culture where pupils are safe?",
                "evidence_criteria": (
                    "• Leaders ensure safeguarding is given highest priority throughout the school\n"
                    "• The DSL is empowered and supported by senior leaders\n"
                    "• Leaders ensure all statutory safeguarding requirements are met\n"
                    "• Leaders respond swiftly and proportionately to safeguarding concerns\n"
                    "• Safeguarding culture permeates all aspects of school life"
                ),
                "urgent_improvement_descriptor": "Leadership and management of safeguarding is failing. Fundamental weaknesses require immediate action.",
                "needs_attention_descriptor": "Leadership and management of safeguarding has significant weaknesses that are limiting the school's effectiveness.",
                "expected_descriptor": "Leadership and management of safeguarding is broadly effective. Most systems work well, though improvement is possible.",
                "strong_descriptor": "Leadership and management of safeguarding is strong. Leaders prioritise safeguarding and create a culture of vigilance.",
                "exceptional_descriptor": "Leadership and management of safeguarding is exceptional. Safeguarding is embedded in all aspects of school life and leaders are exemplary.",
            },
            {
                "name": "Use of Pupil Premium & SEND Funding",
                "order": 5,
                "overview": "Is additional funding used effectively to improve outcomes for disadvantaged pupils and those with SEND?",
                "evidence_criteria": (
                    "• Pupil premium strategy is published, evidence-informed and evaluated annually\n"
                    "• Spending decisions are linked to identified gaps and pupil needs\n"
                    "• Impact of spending is monitored; gaps are narrowing\n"
                    "• SEND funding is allocated to meet pupils' needs as set out in EHCPs/SEN support plans\n"
                    "• Leaders evaluate the impact of SEND provision and adjust accordingly"
                ),
                "urgent_improvement_descriptor": "Leadership and management of targeted funding is failing. Fundamental weaknesses require immediate action.",
                "needs_attention_descriptor": "Leadership and management of targeted funding has significant weaknesses that are limiting the school's effectiveness.",
                "expected_descriptor": "Leadership and management of targeted funding is broadly effective. Most systems work well, though improvement is possible.",
                "strong_descriptor": "Leadership and management of targeted funding is strong. Leaders use funding effectively to close gaps and improve outcomes.",
                "exceptional_descriptor": "Leadership and management of targeted funding is exceptional. Leaders are highly effective and targeted funding has a significant, demonstrable impact.",
            },
        ],
    },
    {
        "name": "Early Years",
        "order": 6,
        "is_safeguarding": False,
        "purpose": (
            "To evaluate the quality of early years education for children from age 2 to the end of "
            "Reception, assessing how well children develop and are prepared for Year 1."
        ),
        "subsections": [
            {
                "name": "EYFS Curriculum & Learning Environment",
                "order": 1,
                "overview": "Is the EYFS curriculum ambitious, well-planned and does the learning environment support development?",
                "evidence_criteria": (
                    "• The EYFS curriculum is ambitious and covers all seven areas of learning\n"
                    "• The environment (inside and outside) is purposefully designed to promote learning and independence\n"
                    "• Resources are well-chosen and accessible to children\n"
                    "• Adult-led and child-initiated activities are well balanced\n"
                    "• Communication and language is prioritised throughout the EYFS"
                ),
                "urgent_improvement_descriptor": "Early years provision for curriculum and learning environment is inadequate and is failing children. Urgent action is required.",
                "needs_attention_descriptor": "Early years provision for curriculum and learning environment has significant weaknesses that are limiting children's development.",
                "expected_descriptor": "Early years provision for curriculum and learning environment meets expectations. Most children develop well and are prepared for Year 1.",
                "strong_descriptor": "Early years provision for curriculum and learning environment is strong. Children make good progress and are well prepared for their next stage.",
                "exceptional_descriptor": "Early years provision for curriculum and learning environment is exceptional. Children flourish and are outstandingly prepared for Year 1 and beyond.",
            },
            {
                "name": "Teaching & Adult Interactions",
                "order": 2,
                "overview": "Do adults interact with children in ways that promote learning, language and development?",
                "evidence_criteria": (
                    "• Adults use questioning, modelling and explanation to extend children's thinking\n"
                    "• Vocabulary is explicitly taught and repeated\n"
                    "• Adults respond warmly and consistently to children's emotional needs\n"
                    "• Staff have good knowledge of child development and use it to plan\n"
                    "• Adults support phonics and early reading effectively from Reception"
                ),
                "urgent_improvement_descriptor": "Early years provision for teaching and adult interactions is inadequate and is failing children. Urgent action is required.",
                "needs_attention_descriptor": "Early years provision for teaching and adult interactions has significant weaknesses that are limiting children's development.",
                "expected_descriptor": "Early years provision for teaching and adult interactions meets expectations. Most children develop well and are prepared for Year 1.",
                "strong_descriptor": "Early years provision for teaching and adult interactions is strong. Children make good progress and are well prepared for their next stage.",
                "exceptional_descriptor": "Early years provision for teaching and adult interactions is exceptional. Children flourish and are outstandingly prepared for Year 1 and beyond.",
            },
            {
                "name": "Assessment & Transitions",
                "order": 3,
                "overview": "Is assessment used well to support children's development and inform transition to Year 1?",
                "evidence_criteria": (
                    "• Baseline assessment is completed accurately and used to plan provision\n"
                    "• Assessment is ongoing and based on observation; it does not create excessive workload\n"
                    "• Reception Baseline Assessment (RBA) is administered correctly\n"
                    "• Information is shared effectively with Year 1 teachers to ensure smooth transition\n"
                    "• SEND children are identified early and receive appropriate support from the outset"
                ),
                "urgent_improvement_descriptor": "Early years provision for assessment and transitions is inadequate and is failing children. Urgent action is required.",
                "needs_attention_descriptor": "Early years provision for assessment and transitions has significant weaknesses that are limiting children's development.",
                "expected_descriptor": "Early years provision for assessment and transitions meets expectations. Most children develop well and are prepared for Year 1.",
                "strong_descriptor": "Early years provision for assessment and transitions is strong. Children make good progress and are well prepared for their next stage.",
                "exceptional_descriptor": "Early years provision for assessment and transitions is exceptional. Children flourish and are outstandingly prepared for Year 1 and beyond.",
            },
            {
                "name": "Parent Partnerships",
                "order": 4,
                "overview": "Do parents feel involved and informed about their child's learning?",
                "evidence_criteria": (
                    "• Parents receive regular, meaningful information about their child's progress\n"
                    "• School actively encourages parents to support learning at home\n"
                    "• Two-way communication is valued and accessible\n"
                    "• Parents from disadvantaged or hard-to-reach communities are engaged"
                ),
                "urgent_improvement_descriptor": "Early years provision for parent partnerships is inadequate and is failing children. Urgent action is required.",
                "needs_attention_descriptor": "Early years provision for parent partnerships has significant weaknesses that are limiting children's development.",
                "expected_descriptor": "Early years provision for parent partnerships meets expectations. Most children develop well and are prepared for Year 1.",
                "strong_descriptor": "Early years provision for parent partnerships is strong. Children make good progress and are well prepared for their next stage.",
                "exceptional_descriptor": "Early years provision for parent partnerships is exceptional. Children flourish and parents are genuine partners in their learning.",
            },
        ],
    },
    {
        "name": "Sixth Form",
        "order": 7,
        "is_safeguarding": False,
        "purpose": (
            "To evaluate the quality of post-16 education, including how well students are taught, "
            "supported and prepared for their next steps."
        ),
        "subsections": [
            {
                "name": "Sixth Form Curriculum",
                "order": 1,
                "overview": "Is the sixth form curriculum ambitious, broad and well-suited to students' needs?",
                "evidence_criteria": (
                    "• A broad range of qualifications is offered including A Levels, vocational and applied courses\n"
                    "• Curriculum is ambitious and prepares students for HE, apprenticeships and employment\n"
                    "• Academic and vocational pathways are of equal quality and ambition\n"
                    "• RSHE and personal development continue into post-16 provision\n"
                    "• Students receive effective IAG to make informed course choices"
                ),
                "urgent_improvement_descriptor": "Sixth form provision for curriculum is seriously inadequate. Students' progress and outcomes are unacceptable.",
                "needs_attention_descriptor": "Sixth form provision for curriculum has significant weaknesses. Student outcomes are below acceptable levels.",
                "expected_descriptor": "Sixth form provision for curriculum meets expectations. Students make reasonable progress and are well supported.",
                "strong_descriptor": "Sixth form provision for curriculum is strong. Students make good progress and outcomes are above expectations.",
                "exceptional_descriptor": "Sixth form provision for curriculum is exceptional. Students flourish, achieve highly and are superbly prepared for the next stage.",
            },
            {
                "name": "Teaching & Learning (Post-16)",
                "order": 2,
                "overview": "Is teaching in the sixth form effective and do students learn and progress well?",
                "evidence_criteria": (
                    "• Teachers have strong subject knowledge appropriate to Level 3 and beyond\n"
                    "• Teaching stretches and challenges all students, including the most able\n"
                    "• Students develop independent learning skills and academic literacy\n"
                    "• Assessment is timely, detailed and drives improvement\n"
                    "• Students who fall behind are identified and supported quickly"
                ),
                "urgent_improvement_descriptor": "Sixth form provision for teaching and learning is seriously inadequate. Students' progress and outcomes are unacceptable.",
                "needs_attention_descriptor": "Sixth form provision for teaching and learning has significant weaknesses. Student outcomes are below acceptable levels.",
                "expected_descriptor": "Sixth form provision for teaching and learning meets expectations. Students make reasonable progress and are well supported.",
                "strong_descriptor": "Sixth form provision for teaching and learning is strong. Students make good progress and outcomes are above expectations.",
                "exceptional_descriptor": "Sixth form provision for teaching and learning is exceptional. Students flourish, achieve highly and are superbly prepared for the next stage.",
            },
            {
                "name": "Outcomes & Destinations",
                "order": 3,
                "overview": "Do students achieve well and progress to appropriate positive destinations?",
                "evidence_criteria": (
                    "• Attainment and progress measures are at least in line with national averages for similar provision\n"
                    "• Retention rates are high; students who begin courses complete them\n"
                    "• The vast majority of students progress to positive destinations (HE, apprenticeship, employment)\n"
                    "• Disadvantaged students' outcomes are closely monitored and gaps are narrowing\n"
                    "• Destinations data is used to evaluate and improve provision"
                ),
                "urgent_improvement_descriptor": "Sixth form provision for outcomes and destinations is seriously inadequate. Students' progress and outcomes are unacceptable.",
                "needs_attention_descriptor": "Sixth form provision for outcomes and destinations has significant weaknesses. Student outcomes are below acceptable levels.",
                "expected_descriptor": "Sixth form provision for outcomes and destinations meets expectations. Students make reasonable progress and are well supported.",
                "strong_descriptor": "Sixth form provision for outcomes and destinations is strong. Students make good progress and outcomes are above expectations.",
                "exceptional_descriptor": "Sixth form provision for outcomes and destinations is exceptional. Students flourish, achieve highly and progress to outstanding destinations.",
            },
        ],
    },
    {
        "name": "SEND",
        "order": 8,
        "is_safeguarding": False,
        "purpose": (
            "To evaluate how well the school identifies, supports and meets the needs of pupils "
            "with special educational needs and disabilities."
        ),
        "subsections": [
            {
                "name": "Identification & Assessment",
                "order": 1,
                "overview": "Does the school identify pupils with SEND early and assess their needs accurately?",
                "evidence_criteria": (
                    "• SEND is identified early through robust assessment processes\n"
                    "• The SENCO is appropriately qualified and has sufficient time and influence\n"
                    "• Pupils who may have SEND are assessed using evidence-based tools\n"
                    "• The SEND register is accurate and kept up to date\n"
                    "• Pupils who are disadvantaged are not misidentified as having SEND"
                ),
                "urgent_improvement_descriptor": "SEND provision for identification and assessment is seriously failing pupils with SEND. Their needs are not met and outcomes are unacceptable.",
                "needs_attention_descriptor": "SEND provision for identification and assessment has significant weaknesses. Pupils with SEND are not well supported and outcomes are below acceptable levels.",
                "expected_descriptor": "SEND provision for identification and assessment broadly meets expectations. Most pupils with SEND are supported well and make reasonable progress.",
                "strong_descriptor": "SEND provision for identification and assessment is strong. Pupils with SEND are well supported, their needs are met and they make good progress.",
                "exceptional_descriptor": "SEND provision for identification and assessment is exceptional. Pupils with SEND thrive; their needs are expertly met and they achieve excellent outcomes.",
            },
            {
                "name": "Teaching & Adaptations",
                "order": 2,
                "overview": "Does quality first teaching meet the needs of pupils with SEND without limiting ambition?",
                "evidence_criteria": (
                    "• Teachers understand pupils' SEND needs and adapt teaching accordingly\n"
                    "• Adaptations are made without reducing the ambition or quality of the curriculum\n"
                    "• Teaching assistants are deployed effectively to support SEND pupils' independence\n"
                    "• Staff receive CPD on SEND; they can explain the strategies they use\n"
                    "• SEND pupils have access to the same breadth of curriculum as their peers"
                ),
                "urgent_improvement_descriptor": "SEND provision for teaching and adaptations is seriously failing pupils with SEND. Their needs are not met and outcomes are unacceptable.",
                "needs_attention_descriptor": "SEND provision for teaching and adaptations has significant weaknesses. Pupils with SEND are not well supported and outcomes are below acceptable levels.",
                "expected_descriptor": "SEND provision for teaching and adaptations broadly meets expectations. Most pupils with SEND are supported well and make reasonable progress.",
                "strong_descriptor": "SEND provision for teaching and adaptations is strong. Pupils with SEND are well supported, their needs are met and they make good progress.",
                "exceptional_descriptor": "SEND provision for teaching and adaptations is exceptional. Pupils with SEND thrive; their needs are expertly met and they achieve excellent outcomes.",
            },
            {
                "name": "EHCP Quality & Review",
                "order": 3,
                "overview": "Are EHCPs of high quality, and are annual reviews conducted effectively?",
                "evidence_criteria": (
                    "• EHCPs are person-centred and reflect current needs, strengths and aspirations\n"
                    "• Outcomes in EHCPs are specific, measurable and ambitious\n"
                    "• Annual reviews are conducted on time and result in meaningful plan updates\n"
                    "• Parents and pupils are genuinely involved in reviews\n"
                    "• Provision specified in EHCPs is delivered in full"
                ),
                "urgent_improvement_descriptor": "SEND provision for EHCP quality and review is seriously failing pupils with SEND. Their needs are not met and outcomes are unacceptable.",
                "needs_attention_descriptor": "SEND provision for EHCP quality and review has significant weaknesses. Pupils with SEND are not well supported and outcomes are below acceptable levels.",
                "expected_descriptor": "SEND provision for EHCP quality and review broadly meets expectations. Most pupils with SEND are supported well and make reasonable progress.",
                "strong_descriptor": "SEND provision for EHCP quality and review is strong. Pupils with SEND are well supported, their needs are met and they make good progress.",
                "exceptional_descriptor": "SEND provision for EHCP quality and review is exceptional. Pupils with SEND thrive; their needs are expertly met and they achieve excellent outcomes.",
            },
            {
                "name": "Parental Engagement (SEND)",
                "order": 4,
                "overview": "Are parents of pupils with SEND engaged as partners in their child's education?",
                "evidence_criteria": (
                    "• Parents receive clear, regular information about their child's SEND provision and progress\n"
                    "• Parents feel listened to and involved in decision-making\n"
                    "• School signposts parents to relevant support and the Local Offer\n"
                    "• Complaints from parents about SEND are taken seriously and resolved promptly"
                ),
                "urgent_improvement_descriptor": "SEND provision for parental engagement is seriously failing pupils with SEND. Their needs are not met and outcomes are unacceptable.",
                "needs_attention_descriptor": "SEND provision for parental engagement has significant weaknesses. Pupils with SEND are not well supported and outcomes are below acceptable levels.",
                "expected_descriptor": "SEND provision for parental engagement broadly meets expectations. Most pupils with SEND are supported well and make reasonable progress.",
                "strong_descriptor": "SEND provision for parental engagement is strong. Pupils with SEND are well supported and parents are genuine partners.",
                "exceptional_descriptor": "SEND provision for parental engagement is exceptional. Parents are exemplary partners; pupils with SEND thrive and achieve excellent outcomes.",
            },
            {
                "name": "Outcomes for Pupils with SEND",
                "order": 5,
                "overview": "Do pupils with SEND make good progress relative to their starting points?",
                "evidence_criteria": (
                    "• Pupils with SEND make progress in line with or better than their individual targets\n"
                    "• Pupils with SEND develop independence, communication and life skills\n"
                    "• Attendance for pupils with SEND is at least in line with the whole school\n"
                    "• Exclusion rates for SEND pupils are not disproportionate\n"
                    "• Pupils with SEND are prepared effectively for their next stage of education or adult life"
                ),
                "urgent_improvement_descriptor": "SEND provision for outcomes is seriously failing pupils with SEND. Their needs are not met and outcomes are unacceptable.",
                "needs_attention_descriptor": "SEND provision for outcomes has significant weaknesses. Pupils with SEND are not well supported and outcomes are below acceptable levels.",
                "expected_descriptor": "SEND provision for outcomes broadly meets expectations. Most pupils with SEND are supported well and make reasonable progress.",
                "strong_descriptor": "SEND provision for outcomes is strong. Pupils with SEND are well supported, their needs are met and they make good progress.",
                "exceptional_descriptor": "SEND provision for outcomes is exceptional. Pupils with SEND thrive; their needs are expertly met and they achieve excellent outcomes.",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "Load all in-depth review areas and sub-sections from the Ofsted "
        "Inspection Toolkit Blueprint (v1.1, November 2025)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            default=False,
            help="Delete ALL existing InDepthArea and InDepthSubSection records before loading.",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write("Clearing existing areas and sub-sections...")
            InDepthSubSection.objects.all().delete()
            InDepthArea.objects.all().delete()

        created_areas = updated_areas = created_subs = updated_subs = 0

        blueprint_names = {a["name"] for a in BLUEPRINT}

        with transaction.atomic():
            # Remove any area that is no longer part of the blueprint.
            stale_qs = InDepthArea.objects.exclude(name__in=blueprint_names)
            stale_count = stale_qs.count()
            if stale_count:
                stale_qs.delete()
                self.stdout.write(f"Removed {stale_count} legacy area(s) not in blueprint.")

            for area_data in BLUEPRINT:
                subsections = area_data.pop("subsections")
                area, created = InDepthArea.objects.update_or_create(
                    name=area_data["name"],
                    defaults={
                        "order": area_data["order"],
                        "is_safeguarding": area_data["is_safeguarding"],
                        "purpose": area_data.get("purpose", ""),
                    },
                )
                if created:
                    created_areas += 1
                else:
                    updated_areas += 1

                for sub_data in subsections:
                    sub, created = InDepthSubSection.objects.update_or_create(
                        area=area,
                        name=sub_data["name"],
                        defaults={
                            "order": sub_data.get("order", 0),
                            "overview": sub_data.get("overview", ""),
                            "evidence_criteria": sub_data.get("evidence_criteria", ""),
                            "urgent_improvement_descriptor": sub_data.get("urgent_improvement_descriptor", ""),
                            "needs_attention_descriptor": sub_data.get("needs_attention_descriptor", ""),
                            "expected_descriptor": sub_data.get("expected_descriptor", ""),
                            "strong_descriptor": sub_data.get("strong_descriptor", ""),
                            "exceptional_descriptor": sub_data.get("exceptional_descriptor", ""),
                            "not_met_descriptor": sub_data.get("not_met_descriptor", ""),
                            "met_descriptor": sub_data.get("met_descriptor", ""),
                        },
                    )
                    if created:
                        created_subs += 1
                    else:
                        updated_subs += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Areas: {created_areas} created, {updated_areas} updated. "
                f"Sub-sections: {created_subs} created, {updated_subs} updated."
            )
        )
